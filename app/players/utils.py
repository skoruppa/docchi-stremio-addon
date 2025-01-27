import re


def unpack_js(encoded_js):  # based on https://github.com/LcdoWalterGarcia/Luluvdo-Link-Direct/blob/main/JavaScriptUnpacker.php
    match = re.search(r"}\('(.*)', *(\d+), *(\d+), *'(.*?)'\.split\('\|'\)", encoded_js)
    if not match:
        return ""

    payload, radix, count, symtab = match.groups()
    radix, count = int(radix), int(count)
    symtab = symtab.split('|')

    if len(symtab) != count:
        raise ValueError("Malformed p.a.c.k.e.r symtab")

    def unbase(val):
        alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'[:radix]
        base_dict = {char: index for index, char in enumerate(alphabet)}
        result = 0
        for i, char in enumerate(reversed(val)):
            result += base_dict[char] * (radix ** i)
        return result

    def lookup(match):
        word = match.group(0)
        index = unbase(word)
        return symtab[index] if index < len(symtab) else word

    decoded = re.sub(r'\b\w+\b', lookup, payload)
    return decoded.replace('\\', '')