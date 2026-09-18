import { BLACKLISTED_ADDRESSES } from "../blacklist";

export const BLACKLIST = new Set([...BLACKLISTED_ADDRESSES,
  "0x28c6c06298d514db089934071355e5743bf21d60",
  "0xae2fc483527b8ef99eb5d9b44875f005ba1fae13",
  "0x00000000003b3cc22af3ae1eac0440bcee416b40",
  "0x47ac0fb4f2d84898e4d9e7b4dab3c24507a6d503",
  "0x1111111254eeb25477b68fb85ed929f73a960582",
  "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
].map((address) => address.toLowerCase()));

export function isBlacklisted(address: string): boolean {
  return BLACKLIST.has(address.startsWith("0x") ? address.toLowerCase() : address);
}
