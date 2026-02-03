"""
JavaScript unpacker for p.a.c.k.e.r packed code.
Adapted from ResolveUrl Kodi Addon.
"""

import re


def detect(source):
    """Detects whether source is P.A.C.K.E.R. coded."""
    return re.search(r"eval[ ]*\([ ]*function[ ]*\([ ]*p[ ]*,[ ]*a[ ]*,[ ]*c[ ]*,[ ]*k[ ]*,[ ]*e[ ]*,[ ]*", source) is not None


def unpack(source):
    """Unpacks P.A.C.K.E.R. packed js code."""
    payload, symtab, radix, count = _filterargs(source)

    if count != len(symtab):
        return ""

    try:
        unbase = Unbaser(radix)
    except TypeError:
        return ""

    def lookup(match):
        """Look up symbols in the synthetic symtab."""
        word = match.group(0)
        return symtab[unbase(word)] or word

    payload = payload.replace("\\\\", "\\").replace("\\'", "'")
    
    source = re.sub(r"\b\w+\b", lookup, payload)
    return source


def _filterargs(source):
    """Extract the four args needed by decoder."""
    argsregex = r"}\s*\('(.*)'\s*,\s*(.*?)\s*,\s*(\d+)\s*,\s*'(.*?)'\.split\('\|'\)"
    args = re.search(argsregex, source, re.DOTALL)
    
    if not args:
        raise ValueError("Cannot find packed data")
    
    payload, radix, count, symtab = args.groups()
    radix = 36 if not radix.isdigit() else int(radix)
    return payload, symtab.split('|'), radix, int(count)


class Unbaser:
    """Functor for a given base. Converts strings to natural numbers."""
    ALPHABET = {
        62: '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
        95: (r' !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ'
             r'[\]^_`abcdefghijklmnopqrstuvwxyz{|}~')
    }

    def __init__(self, base):
        self.base = base

        if 2 <= base <= 36:
            self.unbase = lambda string: int(string, base)
        else:
            if base < 62:
                self.ALPHABET[base] = self.ALPHABET[62][0:base]
            elif 62 < base < 95:
                self.ALPHABET[base] = self.ALPHABET[95][0:base]
            
            try:
                self.dictionary = dict((cipher, index) for index, cipher in enumerate(self.ALPHABET[base]))
            except KeyError:
                raise TypeError('Unsupported base encoding.')

            self.unbase = self._dictunbaser

    def __call__(self, string):
        return self.unbase(string)

    def _dictunbaser(self, string):
        """Decodes a value to an integer."""
        ret = 0
        for index, cipher in enumerate(string[::-1]):
            ret += (self.base ** index) * self.dictionary[cipher]
        return ret
