import logging, os
from datetime import datetime

from ..parser import wdefs
from .wnamerow import NameRow



class Namedumper(object):
    EMPTY_BANKTYPE = ''

    def __init__(self, wnames, cfg, names, missing, bankpaths):
        # flags
        self._wnames = wnames
        self._cfg = cfg
        self._names = names
        self._missing = missing
        self._bankpaths = bankpaths
        self._conditionals = set()
        self._is_bank_mixed = self._get_bank_mixed()


    # true if there are sfx and localized, false if all are from the same type
    def _get_bank_mixed(self):
        is_sfx = False
        is_lang = False
        for _, loc in self._bankpaths.keys():
            if loc:
                is_lang = True
            else:
                is_sfx = True

        return is_lang and is_sfx


    # saves loaded hashnames to .txt
    # (useful to check names when loading generic db/lst of names)
    def save_lst(self, basename=None, path=None):

        # setup
        if not basename:
            basename = 'banks'
        else:
            basename = os.path.basename(basename)
        time = datetime.today().strftime('%Y%m%d%H%M%S')
        outname = 'wwnames-%s-%s.txt' % (basename, time)
        if path:
            outname = os.path.join(path, outname)

        logging.info("names: saving %s" % (outname))

        lines = self.get_lines()

        # final output
        with open(outname, 'w', encoding='utf-8') as outfile:
            config_lines = self._cfg.get_config_lines()
            outfile.write('\n'.join(config_lines))

            outfile.write('\n'.join(lines))

    def get_lines(self):
        has_companion_names = False
        names = self._names.values()
        rows = []

        # conditionals: some IDs detect if are reversable by the existence of other "origin" IDs, mark those
        for hashtype in self._missing:
            if hashtype not in wdefs.fnv_conditionals_origin:
                continue
            # [hashtype] = {(bank, localized)} = [ids]
            for ids in self._missing[hashtype].values():
                for id in ids:
                    self._conditionals.add(id)

        # save valid names
        for row in names:
            # hashnames only, as they can be safely shared between games
            if not row.hashname:
                continue
            # used names only, unless set to save all
            if not self._cfg.save_all and not row.hashname_used:
                continue
            # names not in xml/h/etc only, unless set to save extra
            if not self._cfg.save_companion and row.source != NameRow.NAME_SOURCE_EXTRA:
                has_companion_names = True
                continue

            # conditionals: same as above but for existing names, that don't go to missing
            if row.hashtypes:
                row_hashtypes_only = [item[0] for item in row.hashtypes] # (hashtype, bankkey)
                if any(x in row_hashtypes_only for x in wdefs.fnv_conditionals_origin):
                    self._conditionals.add(row.id)

            rows.append(row)

        if self._cfg.classify_bank:
            # clasified list: include rows divided into sections
            lines = self._include_classify(rows)
        else:
            # simple list: include rows as-is
            lines = self._include_simple(rows)

        if has_companion_names:
            lines.append("\n### (more names found in companion files)\n")

        return lines

    def _include_simple(self, rows):
        lines = []
        for row in rows:
            self._save_lst_name(row, lines)

        # write IDs that don't should have hashnames but don't
        for hashtype in wdefs.fnv_order:
            if hashtype not in self._missing:
                continue
            banks = self._missing[hashtype]
            for bank in banks:
                lines += self._include_missing(hashtype, bank, header=True)

        return lines

    # clasified list: include rows divided into sections
    def _include_classify(self, rows):
        lines = []

        hashtypes_lines = {}

        bankkey_empty = (self.EMPTY_BANKTYPE, False)

        # save names in temp sublines per bank (ids not in names are in self._missing)
        for row in rows:
            hashtypes = row.hashtypes
            if not hashtypes:
                hashtypes = set()
                hashkey = (wdefs.fnv_no, bankkey_empty)
                hashtypes.add(hashkey)

            for hashtype, bankkey in hashtypes:
                banks_lines = hashtypes_lines.get(hashtype)
                if not banks_lines:
                    banks_lines = {}
                    hashtypes_lines[hashtype] = banks_lines

                sublines = banks_lines.get(bankkey)
                if not sublines:
                    sublines = []
                    banks_lines[bankkey] = sublines

                self._save_lst_name(row, sublines)

        # get banks to write
        bankkeys = [bankkey_empty] #special value for other names
        bankkeys += list(self._bankpaths.keys()) #all bankkeys

        # sort by: general names > init > localized names
        def sorter(x):
            bankname, bank_loc = x

            # for hash banks use name if possible
            if bankname and bankname.isdigit():
                row = self._wnames.get_namerow(bankname)
                if row and row.hashname:
                    bankname = row.hashname

            not_init = bankname.lower() not in ['init','1355168291'] #TODO: detect renamed init.bnk

            return (bankname != self.EMPTY_BANKTYPE, not_init, bank_loc, bankname)
        bankkeys.sort(key=sorter)

        # may print like: bank > hashtypes (banks_first=True), or hashtypes > banks (mainly a test)
        banks_first = True
        if banks_first:
            for bankkey in bankkeys:
                for hashtype in wdefs.fnv_order:
                    self._include_classify_lines(lines, hashtypes_lines, hashtype, bankkey)
        else:
            for hashtype in wdefs.fnv_order:
                for bankkey in bankkeys:
                    self._include_classify_lines(lines, hashtypes_lines, hashtype, bankkey)

        lines.append('')
        return lines

    def _include_classify_lines(self, lines, types_lines, hashtype, bankkey):
        save_missing = self._cfg.save_missing
        if hashtype not in types_lines and not save_missing:
            return
        bankkeys = types_lines.get(hashtype)

        if not bankkeys or bankkey not in bankkeys:
            banks_missing = self._missing.get(hashtype)
            if not banks_missing or bankkey not in banks_missing:
                return
            sublines = None
        else:
            sublines = bankkeys.get(bankkey)

        missing_lines = None
        # include missing ids at bank level (otherwise at the end)
        if save_missing:
            missing_lines = self._include_missing(hashtype, bankkey)

        if not sublines and not missing_lines:
            return


        lines.append('')
        banktext = self._get_banktext(bankkey)
        if banktext:
            banktext = " (%s)" % (banktext)
        lines.append('### %s NAMES%s' % (hashtype.upper(), banktext))

        if sublines:
            sublines.sort(key=str.lower)
            for subline in sublines:
                lines.append(subline)

        if missing_lines:
            lines += missing_lines


    def _include_missing(self, hashtype, bank, header=False):
        lines = []
        if self._cfg.skip_hashtype(hashtype):
            return lines

        banks = self._missing.get(hashtype)
        if not banks:
            return lines
        ids = banks.get(bank)
        if not ids:
            return lines

        if header:
            lines.append('')
            banktext = self._get_banktext(bank)
            if banktext:
                banktext = " (%s)" % (banktext)
            lines.append('### MISSING %s NAMES%s' % (hashtype.upper(), banktext))

        for id in ids:
            # some IDs may point to hashnames or guidnames, find out if safe to print
            # (this info is preloaded at the beginning)
            if hashtype in wdefs.fnv_conditionals:
                if id not in self._conditionals:
                    continue

            lines.append('# %s' % (id))

        # remove so it doesn't get saved twice
        banks[bank] = {}
        return lines

    # bank info used in sections: '### BLAH (banktext)'
    def _get_banktext(self, bankkey):
        bankname, bank_loc = bankkey
        if not bankname:
            return ''

        bankpath_full, bankfile = self._bankpaths.get(bankkey)

        # remove multiple extensions from RE Engine style names
        if '.bnk.' in bankfile:
            index = bankfile.find('.bnk.')
            bankfile = bankfile[: index + 4]

        # optional info
        bankpath = ''
        if self._cfg.bank_paths:
            bankpath = bankpath_full
        elif bank_loc is True and self._is_bank_mixed:
            # mark localized banks if there are localized and non-localized banks (as some games may use only localized)
            bankpath = 'langs'

        if bankpath:
            bankpath = bankpath.replace('\\', '/')
            bankfile = "%s/%s" % (bankpath, bankfile)

        # bank is a regular name
        if not bankname.isdigit():
            return bankfile

        # bank is a number and has hashname
        row = self._wnames.get_namerow(bankname)
        if row and row.hashname:
            return "%s: %s" % (bankfile, row.hashname)

        # plain name (with or without path)
        return bankfile

    def _save_lst_name(self, row, lines):
        #logging.debug("names: using '%s'", row.hashname)
        extended = ''
        if row.extended:
            extended = ' = 0' #allow names with special chars
        lines.append('%s%s' % (row.hashname, extended))

        # log alts too (list should be cleaned up manually)
        for hashname in row.hashnames:
            if extended:
                lines.append('#alt')
                lines.append('%s%s' % (row.hashname, extended))
            else:
                lines.append('%s #alt' % (hashname))
