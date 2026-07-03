// Manual base64url decode (no atob/Buffer dependency -- not guaranteed
// present in the Hermes JS engine) to read the JWT payload client-side.
// Mirrors frontend/app.js's parseJwt() -- read-only, never used for
// verification (the backend is the source of truth for auth).
const BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

function base64Decode(input: string): string {
  let str = input.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4) str += "=";
  let output = "";
  let buffer = 0;
  let bits = 0;
  for (const char of str) {
    if (char === "=") break;
    const value = BASE64_CHARS.indexOf(char);
    if (value === -1) continue;
    buffer = (buffer << 6) | value;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      output += String.fromCharCode((buffer >> bits) & 0xff);
    }
  }
  return output;
}

export function decodeJwtPayload(token: string): { sub?: string; org?: string; exp?: number } {
  try {
    const payload = token.split(".")[1];
    const json = decodeURIComponent(
      base64Decode(payload)
        .split("")
        .map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0"))
        .join("")
    );
    return JSON.parse(json);
  } catch {
    return {};
  }
}
