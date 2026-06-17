const ORDINALS = [
  "", "Pertama", "Kedua", "Ketiga", "Keempat", "Kelima",
  "Keenam", "Ketujuh", "Kedelapan", "Kesembilan", "Kesepuluh",
];


const NUM_WORDS = ["nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan"];
const SCALE_WORDS = [[1000000000000, "triliun"], [1000000000, "miliar"], [1000000, "juta"], [1000, "ribu"]];
const SCALE_ALIASES = { ribu: "ribu", juta: "juta", miliar: "miliar", milyar: "miliar", miliyar: "miliar", triliun: "triliun", teriliun: "triliun" };
const SCALE_PATTERN = "ribu|juta|miliar|milyar|miliyar|triliun|teriliun";
const NUMBER_TOKEN = "\\d{1,3}(?:\\.\\d{3})+|\\d+(?:[,.]\\d+)?";
const RANGE_SEP = "(?:-|–|—|s/d|sd|sampai|hingga)";

function underThousandToWords(number) {
  if (number < 10) return NUM_WORDS[number];
  if (number === 10) return "sepuluh";
  if (number === 11) return "sebelas";
  if (number < 20) return `${NUM_WORDS[number - 10]} belas`;
  if (number < 100) {
    const tens = Math.floor(number / 10);
    const rest = number % 10;
    const words = `${NUM_WORDS[tens]} puluh`;
    return rest ? `${words} ${underThousandToWords(rest)}` : words;
  }
  const hundreds = Math.floor(number / 100);
  const rest = number % 100;
  const words = hundreds === 1 ? "seratus" : `${NUM_WORDS[hundreds]} ratus`;
  return rest ? `${words} ${underThousandToWords(rest)}` : words;
}

function numberToIndonesianWords(number) {
  if (number < 0) return `minus ${numberToIndonesianWords(Math.abs(number))}`;
  if (number < 1000) return underThousandToWords(number);
  const parts = [];
  let remainder = number;
  for (const [scale, label] of SCALE_WORDS) {
    const value = Math.floor(remainder / scale);
    remainder %= scale;
    if (!value) continue;
    if (scale === 1000 && value === 1) parts.push("seribu");
    else parts.push(`${numberToIndonesianWords(value)} ${label}`);
  }
  if (remainder) parts.push(underThousandToWords(remainder));
  return parts.join(" ");
}

function spokenDecimalNumber(value) {
  const [integer, decimal = ""] = value.split(/[,.]/, 2);
  const integerWords = numberToIndonesianWords(Number(integer || 0));
  const decimalWords = [...decimal].filter((char) => /\d/.test(char)).map((char) => NUM_WORDS[Number(char)]).join(" ");
  return decimalWords ? `${integerWords} koma ${decimalWords}` : integerWords;
}


function numberTokenToWords(value) {
  const raw = String(value || "").trim();
  if (/^\d{1,3}(?:\.\d{3})+$/.test(raw)) return numberToIndonesianWords(Number(raw.replace(/\./g, "")));
  if (/^\d+[,.]\d+$/.test(raw)) return spokenDecimalNumber(raw);
  return numberToIndonesianWords(Number(raw));
}

function normalizeSpokenRanges(text) {
  return String(text || "")
    .replace(new RegExp(`\\b(?:Rp\\.?|IDR)\\s*(${NUMBER_TOKEN})\\s*${RANGE_SEP}\\s*(?:Rp\\.?|IDR)?\\s*(${NUMBER_TOKEN})\\b`, "gi"), (_, left, right) => `${numberTokenToWords(left)} rupiah hingga ${numberTokenToWords(right)} rupiah`)
    .replace(new RegExp(`\\b(${NUMBER_TOKEN})\\s*(${SCALE_PATTERN})?\\s*${RANGE_SEP}\\s*(${NUMBER_TOKEN})\\s*(${SCALE_PATTERN})\\b`, "gi"), (_, left, leftScale, right, rightScale) => {
      const normalizedLeftScale = leftScale ? SCALE_ALIASES[leftScale.toLowerCase()] : "";
      const normalizedRightScale = SCALE_ALIASES[rightScale.toLowerCase()];
      if (normalizedLeftScale && normalizedLeftScale !== normalizedRightScale) return `${numberTokenToWords(left)} ${normalizedLeftScale} hingga ${numberTokenToWords(right)} ${normalizedRightScale}`;
      return `${numberTokenToWords(left)} hingga ${numberTokenToWords(right)} ${normalizedRightScale}`;
    })
    .replace(new RegExp(`\\b(${NUMBER_TOKEN})\\s*%\\s*${RANGE_SEP}\\s*(${NUMBER_TOKEN})\\s*%(?=\\W|$)`, "gi"), (_, left, right) => `${numberTokenToWords(left)} hingga ${numberTokenToWords(right)} persen`)
    .replace(new RegExp(`\\b(${NUMBER_TOKEN})\\s*${RANGE_SEP}\\s*(${NUMBER_TOKEN})\\s*%(?=\\W|$)`, "gi"), (_, left, right) => `${numberTokenToWords(left)} hingga ${numberTokenToWords(right)} persen`)
    .replace(new RegExp(`\\b(${NUMBER_TOKEN})\\s*${RANGE_SEP}\\s*(${NUMBER_TOKEN})\\s*(hari|bulan|tahun|minggu|orang|unit|produk|kali|x)?\\b`, "gi"), (_, left, right, unit = "") => `${numberTokenToWords(left)} hingga ${numberTokenToWords(right)}${unit ? ` ${unit}` : ""}`);
}

function normalizeSpokenNumbers(text) {
  const currency = (_, raw) => `${numberToIndonesianWords(Number(raw.replace(/\./g, "")))} rupiah`;
  return normalizeSpokenRanges(text)
    .replace(/\b(?:Rp\.?|IDR)\s*(\d{1,3}(?:\.\d{3})+)\b/gi, currency)
    .replace(/\b(\d{1,3}(?:\.\d{3})+)\s*(?:rupiah|idr)\b/gi, currency)
    .replace(/\b\d{1,3}(?:\.\d{3})+\b/g, (value) => numberToIndonesianWords(Number(value.replace(/\./g, ""))))
    .replace(new RegExp(`\\b(\\d+[,.]\\d+)\\s*(${SCALE_PATTERN})\\b`, "gi"), (_, value, scale) => `${spokenDecimalNumber(value)} ${SCALE_ALIASES[scale.toLowerCase()]}`)
    .replace(new RegExp(`\\b(\\d+)\\s*(${SCALE_PATTERN})\\b`, "gi"), (_, value, scale) => `${numberToIndonesianWords(Number(value))} ${SCALE_ALIASES[scale.toLowerCase()]}`)
    .replace(/\b\d{4,15}\b/g, (value) => Number(value) >= 1000 ? numberToIndonesianWords(Number(value)) : value);
}

export function normalizeSpeechText(text) {
  return String(text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/https?:\/\/\S+/g, " tautan ")
    .replace(/^\s*#{1,6}\s+/gm, "")
    .replace(/^\s*(\d{1,2})[.)]\s+/gm, (_, value) => `${ORDINALS[Number(value)] || `Nomor ${value}`}, `)
    .replace(/^\s*[-*•]\s+/gm, "")
    .replace(/[\s\S]*/, (value) => normalizeSpokenNumbers(value))
    .replace(/[;]+/g, ",")
    .replace(/[:]+(?=\s)/g, ",")
    .replace(/[!?]{2,}/g, (value) => value[0])
    .replace(/\.{3,}/g, ".")
    .replace(/[*_`#>|~]/g, " ")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/([.!?,])?\s*\n{2,}\s*/g, (_, punctuation) => punctuation ? `${punctuation} ` : ". ")
    .replace(/\s*\n\s*/g, " ")
    .replace(/\s+([,.;!?])/g, "$1")
    .replace(/([.!?])(?=[A-Za-zÀ-ÿ])/g, "$1 ")
    .replace(/,{2,}/g, ",")
    .replace(/([.!?]){2,}/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function splitLongSentence(sentence, maxLength) {
  if (sentence.length <= maxLength) return [sentence];
  const parts = [];
  const words = sentence.split(/\s+/);
  let current = "";
  for (const word of words) {
    if (current && current.length + word.length + 1 > maxLength) {
      parts.push(current);
      current = word;
    } else {
      current = current ? `${current} ${word}` : word;
    }
  }
  if (current) parts.push(current);
  return parts;
}

export function bufferSpeechSentences(
  text,
  { targetLength = 320, minLength = 55, maxLength = 900 } = {},
) {
  const normalized = normalizeSpeechText(text);
  if (!normalized) return [];
  const sentences = normalized.match(/[^.!?]+(?:[.!?]+|$)/g) || [normalized];
  const chunks = [];
  let current = "";
  for (const rawSentence of sentences) {
    const sentence = rawSentence.trim();
    if (!sentence) continue;
    for (const part of splitLongSentence(sentence, maxLength)) {
      const combined = current ? `${current} ${part}` : part;
      if (current && combined.length > maxLength && current.length >= minLength) {
        chunks.push(current);
        current = part;
      } else {
        current = combined;
      }
      if (current.length >= targetLength && /[.!?]$/.test(current)) {
        chunks.push(current);
        current = "";
      }
    }
  }
  if (current) {
    if (chunks.length && current.length < minLength) {
      chunks[chunks.length - 1] = `${chunks[chunks.length - 1]} ${current}`;
    } else {
      chunks.push(current);
    }
  }
  return chunks;
}

export function segmentPauseMs(text) {
  const ending = String(text || "").trim().slice(-1);
  if (ending === "?" || ending === "!") return 75;
  if (ending === ".") return 55;
  if (ending === ",") return 20;
  return 25;
}
