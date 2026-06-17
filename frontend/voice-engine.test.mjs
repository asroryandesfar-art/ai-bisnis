import test from "node:test";
import assert from "node:assert/strict";
import { bufferSpeechSentences, normalizeSpeechText, segmentPauseMs } from "./voice-engine.js";

test("normalizes whitespace, markdown, and bullets", () => {
  assert.equal(normalizeSpeechText("## Ringkasan\n\n- Satu   hal\n- Dua hal"), "Ringkasan Satu hal Dua hal");
});

test("buffers complete sentences instead of tiny chunks", () => {
  const chunks = bufferSpeechSentences(
    "Ini pendek. Ini juga pendek. Kalimat ketiga melanjutkan penjelasan dengan ritme percakapan yang alami.",
    { targetLength: 70, minLength: 40, maxLength: 180 },
  );
  assert.deepEqual(chunks, ["Ini pendek. Ini juga pendek. Kalimat ketiga melanjutkan penjelasan dengan ritme percakapan yang alami."]);
});

test("keeps commas inside a sentence", () => {
  const chunks = bufferSpeechSentences(
    "Pertama, buka dashboard, lalu pilih agent yang ingin diperbarui. Setelah itu, simpan perubahan.",
    { targetLength: 45, minLength: 20, maxLength: 120 },
  );
  assert.deepEqual(chunks, [
    "Pertama, buka dashboard, lalu pilih agent yang ingin diperbarui.",
    "Setelah itu, simpan perubahan.",
  ]);
});

test("uses sub-200ms punctuation pauses", () => {
  assert.equal(segmentPauseMs("lanjut,"), 20);
  assert.equal(segmentPauseMs("selesai."), 55);
  assert.ok(segmentPauseMs("bertanya?") < 200);
});


test("reads Indonesian grouped numbers naturally", () => {
  assert.equal(
    normalizeSpeechText("Biaya Rp100.000, omzet 1.500.000, target 2 miliar, valuasi 3 triliun."),
    "Biaya seratus ribu rupiah, omzet satu juta lima ratus ribu, target dua miliar, valuasi tiga triliun.",
  );
});


test("accepts Indonesian scale spelling variants", () => {
  assert.equal(normalizeSpeechText("Nilai 5 miliyar dan 7 teriliun."), "Nilai lima miliar dan tujuh triliun.");
});


test("reads Indonesian numeric ranges naturally", () => {
  assert.equal(normalizeSpeechText("Budget 100-500 juta."), "Budget seratus hingga lima ratus juta.");
  assert.equal(normalizeSpeechText("Target 1,5-2 miliar."), "Target satu koma lima hingga dua miliar.");
  assert.equal(normalizeSpeechText("Biaya Rp100.000-Rp500.000."), "Biaya seratus ribu rupiah hingga lima ratus ribu rupiah.");
  assert.equal(normalizeSpeechText("Diskon 10-20% selama 3-5 hari."), "Diskon sepuluh hingga dua puluh persen selama tiga hingga lima hari.");
});
