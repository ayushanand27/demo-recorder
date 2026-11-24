# demo-recorder

Script likho -> ek command -> narrated screen video (mp4).

## Setup (ek baar, Windows)
    pip install playwright edge-tts imageio-ffmpeg
    python -m playwright install chromium

## Chalana
    python record.py examples\demo.json

Options:  --headed (browser dikhe)   --out myvideo.mp4   --tts silent (sirf test)

## Script (JSON) ka format
Har step mein optional `say` (jo bolna hai) aur ek ya zyada actions:

| key | kya karta hai |
|---|---|
| goto | URL ya local file kholta hai (localhost bhi chalega) |
| click | selector par mouse le jaake click (`#btn`, `text=Login`) |
| type | `{"selector": "#q", "text": "hello"}` typing |
| press | key dabata hai (`Enter`) |
| scroll | pixels (negative = upar) |
| run | terminal command dikhata hai (typing + output), `cwd` bhi de sakte ho |
| wait | seconds ruko |
| audio | apni recorded awaaz ki file (say ki jagah) |

Top-level: `voice`, `rate` (jaise "-10%"), `out`, `viewport`, `audio_offset` (seconds).

## Awaaz
- English text -> `en-IN-PrabhatNeural` (ya `en-IN-NeerjaNeural`)
- Hindi -> text Devanagari mein likho aur voice `hi-IN-MadhurNeural` / `hi-IN-SwaraNeural`.
  Roman Hinglish ko Hindi voice galat padhegi.
- edge-tts ko internet chahiye.

## Limits
- Ek browser window record hoti hai (tabs nahi, ek hi page par goto se jaao).
- Desktop apps ya poori screen ke liye alag mode chahiye (agla version).

## Captions (naya)
Har `say` line video pe neeche burn hoti hai (white text, black box). Band karna ho to JSON me `"captions": false`.
Size: `"caption_size": 48`. Saath me `.srt` file bhi banti hai. Voice English hi hai (`en-IN-PrabhatNeural`; US ke liye `en-US-AndrewNeural`).

## Screen mode (WhatsApp Web, Google Sheet, Render... sab ek video me)
JSON me `"mode": "screen"` likho. Real Chrome khulta hai, poora desktop ffmpeg se record hota hai, `"tab"` se tabs switch hote hain.
1. Ek baar login save karo:  `python record.py examples\leadagent_screen.json --setup`  (WhatsApp QR, Google login karke Enter)
2. Phir normal run:  `python record.py examples\leadagent_screen.json`
Run ke time mouse/keyboard mat chhedna, aur doosri window upar mat laana. Docker me ye mode nahi chalega (sirf Windows direct).
