![version](https://img.shields.io/badge/version-17%2B-3E8B93)
![platform](https://img.shields.io/static/v1?label=platform&message=mac-intel%20|%20mac-arm%20|%20win-64&color=blue)
[![license](https://img.shields.io/github/license/miyako/4d-plugin-compact-enc-det)](LICENSE)
![downloads](https://img.shields.io/github/downloads/miyako/4d-plugin-compact-enc-det/total)

# 4d-plugin-compact-enc-det

A 4D plugin wrapping Google's [Compact Encoding Detection](https://github.com/google/compact_enc_det) (CED) library. It inspects a raw byte buffer and returns the most likely character encoding, driven entirely by CED's statistical detector — no OS-level text-encoding API is involved, so behavior is identical on Mac and Windows. The plugin exposes a single command, `CED Detect encoding`, which takes a `Blob` and returns an `Object` describing the detected encoding.

## Summary

| Command | Returns | Purpose |
|---|---|---|
| [`CED Detect encoding`](#ced-detect-encoding) | `Object` | Detect the character encoding of a raw byte buffer |

**Platforms:** Mac and Windows (no platform-specific code paths — CED is pure C++).

---

## Requirements & platform notes

- The command takes its input as a `Blob`, not `Text` — if you're starting from a file, read it with `DOCUMENT TO BLOB` (or equivalent) rather than loading it as text first, since converting to `Text` before detection would require already knowing the encoding.
- An empty blob (`BLOB SIZE` of 0) returns an **empty object** — no `encoding`, `isReliable`, or `bytesConsumed` key at all. Always check `OB Is defined` (or similar) on the result before reading any of its keys.
- The `options` parameter is entirely optional and every one of its properties is independently optional — you can pass no object, an empty object, or an object with just the one hint you care about.
- An unrecognized `corpus` string is **silently ignored**, not rejected — the command falls back to `"WEB_CORPUS"` with no error. Double-check spelling if a corpus hint doesn't seem to be taking effect.
- `encoding` in the result is a plain `Text` value naming the underlying CED enum member (e.g. `"UTF8"`, `"MSFT_CP1252"`) — see [Encoding values](#encoding-values) below for the full list this command can return.

---

## CED Detect encoding

### Syntax

```4d
CED Detect encoding ( data ) → Result
CED Detect encoding ( data ; options ) → Result
```

| Parameter | Type | Description |
|---|---|---|
| `data` | Blob | Mandatory. Raw bytes to detect the encoding of. |
| `options` | Object | Optional. Detection hints — see [Options object](#options-object) below. Omit entirely, pass an empty object, or set only the properties you need. |
| Result | Object | `{ encoding: Text; isReliable: Boolean; bytesConsumed: Real }` on success; an **empty object** if `data` is empty (`BLOB SIZE(data) = 0`). |

#### Options object

| Property | Type | Description |
|---|---|---|
| `ignore7bitMailEncodings` | Boolean | Optional, default `false`. When `true`, suppresses detection of the pure 7-bit encodings (`ISO-2022-JP`/`JIS`, `ISO-2022-CN`, `ISO-2022-KR`, `HZ`, `UTF-7`) in favor of the next-best match. CED's own documentation recommends setting this `true` when `corpus` is `"QUERY_CORPUS"`. |
| `httpCharsetHint` | Text | Optional. The charset from an HTTP `Content-Type` header, if you have one (e.g. `"iso-8859-1"`). Used as a detection hint, not a forced value. |
| `metaCharsetHint` | Text | Optional. The charset from an HTML `<meta charset=...>` tag, if you have one (e.g. `"utf-8"`). Used as a hint, not a forced value. |
| `urlHint` | Text | Optional. The page's URL, or just its top-level domain (e.g. `"com"`, `"jp"`). Used as a hint, not a forced value. |
| `corpus` | Text | Optional, default `"WEB_CORPUS"`. One of `"WEB_CORPUS"`, `"XML_CORPUS"`, `"QUERY_CORPUS"`, `"EMAIL_CORPUS"`. Any other string is silently ignored (falls back to `"WEB_CORPUS"`) — see the note above. Use `"QUERY_CORPUS"` for plain short text rather than markup. |

### Description

The command reads the entire `data` blob and passes it, along with whichever hints you supplied, to CED's `DetectEncoding`. CED's own contract (from its header comments) is worth knowing regardless of language binding:

- **A zero-length input is a special case handled before CED is ever called**: this plugin returns an empty object rather than calling into CED at all (CED's own documented behavior for zero length is to report ASCII/Latin-1, which this plugin does not surface).
- `bytesConsumed` reports how much of the input CED actually examined — for a long buffer, this can be less than the full length; CED is designed to skip quickly over large stretches of plain 7-bit ASCII.
- `isReliable` is `true` only when the detected encoding was roughly 1000× (2¹⁰) more probable than the second-best candidate. Treat a `false` result as "best guess, low confidence" rather than as an error.
- Hints (`httpCharsetHint`, `metaCharsetHint`, `urlHint`) bias detection but never force a result — CED can still return a different encoding if the byte content strongly disagrees with the hint.
- **As of the fixed source in this package** (see the note at the end of this section), an internal error during detection returns whatever partial result had already been built — typically an empty object — rather than leaving the call unanswered. This is a behavior change from the originally-reviewed source, which had no such guarantee; if you're running an older build of this plugin, an internal error could instead leave your calling method waiting indefinitely.

### Example

From the plugin's own test method (`TEST.4dm`):

```4d
//%attributes = {}
C_OBJECT:C1216($params)
C_BLOB:C604($bytes)

$path:=Get 4D folder:C485(Current resources folder:K5:16)+"sample.html"
DOCUMENT TO BLOB:C525($path;$bytes)

$status:=CED Detect encoding ($bytes)

$params:=New object:C1471("ignore7bitMailEncodings";True:C214;"corpus";"QUERY_CORPUS")

$status:=CED Detect encoding ($bytes;$params)
```

A more defensive version that checks for the empty-blob case and reads every result key:

```4d
C_BLOB:C604($bytes)
C_OBJECT:C1216($status)
C_TEXT:C284($encoding)

DOCUMENT TO BLOB:C525($path;$bytes)

If (BLOB SIZE:C605($bytes)>0)
	$status:=CED Detect encoding ($bytes)
	If (OB Is defined:C1231($status;"encoding"))
		$encoding:=$status.encoding
		If ($status.isReliable)
			ALERT:C41("Detected: "+$encoding+" (reliable)")
		Else
			ALERT:C41("Detected: "+$encoding+" (low confidence)")
		End if
	End if
Else
	ALERT:C41("Empty document — nothing to detect")
End if
```

Passing all four hints at once, for a page fetched over HTTP with a known URL and a `<meta>` tag:

```4d
C_OBJECT:C1216($params)
$params:=New object:C1471(\
	"httpCharsetHint";"iso-8859-1";\
	"metaCharsetHint";"utf-8";\
	"urlHint";"example.jp";\
	"corpus";"WEB_CORPUS")

$status:=CED Detect encoding ($bytes;$params)
```

---

## Encoding values

`encoding` is always one of the following `Text` values (mirroring CED's own `Encoding` enum). This plugin does not translate these into 4D's built-in text-encoding constants — if you need to feed the result into a command that expects one of those, you'll need your own mapping table.

| | | | |
|---|---|---|---|
| `ISO_8859_1` | `ISO_8859_2` | `ISO_8859_3` | `ISO_8859_4` |
| `ISO_8859_5` | `ISO_8859_6` | `ISO_8859_7` | `ISO_8859_8` |
| `ISO_8859_9` | `ISO_8859_10` | `ISO_8859_11` | `ISO_8859_13` |
| `ISO_8859_15` | `ISO_8859_8_I` | `JAPANESE_EUC_JP` | `JAPANESE_SHIFT_JIS` |
| `JAPANESE_JIS` | `JAPANESE_CP932` | `CHINESE_BIG5` | `CHINESE_BIG5_CP950` |
| `CHINESE_GB` | `CHINESE_EUC_CN` | `CHINESE_EUC_TW` | `CHINESE_CNS` |
| `KOREAN_EUC_KR` | `ISO_2022_KR` | `ISO_2022_CN` | `GBK` |
| `GB18030` | `BIG5_HKSCS` | `HZ_GB_2312` | `UNICODE` |
| `UTF8` | `UTF8UTF8` | `UTF7` | `UTF16BE` |
| `UTF16LE` | `UTF32BE` | `UTF32LE` | `ASCII_7BIT` |
| `BINARYENC` | `UNKNOWN_ENCODING` | `RUSSIAN_KOI8_R` | `RUSSIAN_KOI8_RU` |
| `RUSSIAN_CP1251` | `RUSSIAN_CP866` | `MSFT_CP1250` | `MSFT_CP1252` |
| `MSFT_CP1253` | `MSFT_CP1254` | `MSFT_CP1255` | `MSFT_CP1256` |
| `MSFT_CP1257` | `MSFT_CP874` | `HEBREW_VISUAL` | `CZECH_CP852` |
| `CZECH_CSN_369103` | `TSCII` | `TAMIL_MONO` | `TAMIL_BI` |
| `TAM_ELANGO` | `TAM_LTTMBARANI` | `TAM_SHREE` | `TAM_TBOOMIS` |
| `TAM_TMNEWS` | `TAM_WEBTAMIL` | `JAGRAN` | `MACINTOSH_ROMAN` |
| `BHASKAR` | `HTCHANAKYA` | `KDDI_SHIFT_JIS` | `DOCOMO_SHIFT_JIS` |
| `SOFTBANK_SHIFT_JIS` | `KDDI_ISO_2022_JP` | `SOFTBANK_ISO_2022_JP` | |

`UNKNOWN_ENCODING` is returned both when CED itself reports it and — **as of the fixed source in this package** — as the fallback for any future CED encoding value not yet mapped in this switch. Earlier builds of this plugin (before that fix) instead returned an object with no `encoding` key at all for such a value; check `OB Is defined` if you need to support running against an older binary.

---

## Error handling & troubleshooting

- **Empty result object, no keys at all.** This means `data` was an empty blob (or, on a fixed build, that an internal error occurred during detection). Always check `OB Is defined(result;"encoding")` before reading `result.encoding`.
- **`corpus` value doesn't seem to change anything.** The property only recognizes the four literal strings listed above; anything else — including a typo — is silently ignored and the default `"WEB_CORPUS"` behavior is used instead. There's no error to catch here; verify the exact spelling.
- **Hints don't override an unexpected detected encoding.** `httpCharsetHint`/`metaCharsetHint`/`urlHint` bias the detector, they don't force a result. If the byte content strongly indicates a different encoding, that wins.
- **`isReliable` is `false`.** This isn't an error condition — it means CED's confidence margin over the second-best match was below its ~1000× threshold. Treat the `encoding` value as a best guess for these results, particularly on short inputs.
- **Calling method appears to hang on a malformed or truncated blob (older builds only).** A build of this plugin from before the fix in this package could leave a caller waiting indefinitely if blob-size retrieval returned an unexpected negative value. If you're not running the fixed source, guard by checking `BLOB SIZE` yourself before calling, and avoid passing blobs assembled from unusual or partial sources.

---

## Quick reference

```4d
C_BLOB:C604($bytes)
C_OBJECT:C1216($params;$status)

DOCUMENT TO BLOB:C525($path;$bytes)

// no hints
$status:=CED Detect encoding ($bytes)

// with hints
$params:=New object:C1471("ignore7bitMailEncodings";True:C214;"corpus";"QUERY_CORPUS")
$status:=CED Detect encoding ($bytes;$params)

If (OB Is defined:C1231($status;"encoding"))
	// $status.encoding : Text  -- see Encoding values table
	// $status.isReliable : Boolean
	// $status.bytesConsumed : Real
End if
```
