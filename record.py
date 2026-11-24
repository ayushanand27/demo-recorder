#!/usr/bin/env python3
"""demo-recorder: turn a JSON script into a narrated screen-recording video.

Usage:  python record.py demo.json [--headed] [--tts edge|silent] [--out video.mp4]
Setup:  pip install playwright edge-tts imageio-ffmpeg
        python -m playwright install chromium
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

CURSOR_JS = """
(() => {
  const d = document.createElement('div');
  d.style.cssText = 'position:fixed;z-index:2147483647;width:20px;height:20px;border-radius:50%;'
    + 'background:rgba(255,60,60,.85);border:2px solid #fff;pointer-events:none;left:-60px;top:-60px;'
    + 'transform:translate(-50%,-50%);box-shadow:0 0 8px rgba(0,0,0,.5)';
  const add = () => document.documentElement.appendChild(d);
  if (document.documentElement) add(); else document.addEventListener('DOMContentLoaded', add);
  addEventListener('mousemove', e => { d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; }, true);
})();
"""

TERM_HTML = """<html><body style="margin:0;background:#0c0c0c;color:#d4d4d4;font:24px Consolas,'Courier New',monospace;padding:32px">
<div id="t" style="white-space:pre-wrap;word-break:break-all"></div></body></html>"""


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FF = ffmpeg_exe()


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        raise RuntimeError("command failed: %s\n%s" % (" ".join(map(str, cmd))[:300], r.stderr[-1500:]))
    return r


def audio_len(path):
    r = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        raise RuntimeError("could not read duration of %s" % path)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def make_audio(text, voice, rate, out, engine):
    if engine == "edge":
        import edge_tts
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(out)))
        except Exception as e:
            raise RuntimeError("edge-tts failed (needs internet): %s" % e)
    else:  # quiet test tone, length from word count
        secs = max(1.0, len(text.split()) * 0.4)
        run([FF, "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=%s" % secs,
             "-filter:a", "volume=0.1", str(out)])


def ass_time(t):
    t = max(0.0, t)
    return "%d:%02d:%05.2f" % (int(t // 3600), int(t % 3600 // 60), t % 60)


def make_ass(caps, W, H, path, size):
    """caps = [(start, end, text)]. Long lines are split into chunks of ~8 words."""
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
            "Style: Default,Arial,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,3,3,0,2,"
            "%d,%d,%d,1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
            % (W, H, size, int(W * 0.08), int(W * 0.08), int(H * 0.06)))
    lines = []
    for a, b, text in caps:
        words = text.split()
        chunks = [" ".join(words[i:i + 8]) for i in range(0, len(words), 8)] or [text]
        total = sum(len(c) for c in chunks) or 1
        t = a
        for c in chunks:
            d = (b - a) * len(c) / total
            lines.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (ass_time(t), ass_time(t + d), c.replace("\n", " ")))
            t += d
    Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def srt_time(t):
    return "%02d:%02d:%02d,%03d" % (int(t // 3600), int(t % 3600 // 60), int(t % 60), int(t % 1 * 1000))


def resolve_url(u, base):
    if "://" in u or u.startswith("about:"):
        return u
    return (base / u).resolve().as_uri()


def term_run(page, cmd, cwd, base):
    page.set_content(TERM_HTML)
    page.evaluate("window.out=document.getElementById('t')")
    add = lambda s: page.evaluate("s=>{out.textContent+=s;window.scrollTo(0,document.body.scrollHeight)}", s)
    add("$ ")
    for ch in cmd:
        add(ch)
        time.sleep(0.04)
    time.sleep(0.4)
    add("\n")
    wd = str((base / cwd).resolve()) if cwd else str(base)
    try:
        r = subprocess.run(cmd, shell=True, cwd=wd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90)
        text = ANSI.sub("", (r.stdout or "") + (r.stderr or ""))
    except subprocess.TimeoutExpired:
        text = "(command timed out)"
    for line in text.splitlines()[:60]:
        add(line + "\n")
        time.sleep(0.05)
    add("$ ")


def do_actions(page, step, base):
    if "goto" in step:
        page.goto(resolve_url(step["goto"], base), wait_until="load")
        time.sleep(0.8)
    if "run" in step:
        term_run(page, step["run"], step.get("cwd"), base)
    if "click" in step:
        loc = page.locator(step["click"]).first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y, steps=35)
        time.sleep(0.3)
        page.mouse.click(x, y)
        time.sleep(0.6)
    if "type" in step:
        t = step["type"]
        loc = page.locator(t["selector"]).first
        box = loc.bounding_box()
        page.mouse.move(box["x"] + 20, box["y"] + box["height"] / 2, steps=30)
        loc.click()
        page.keyboard.type(os.path.expandvars(t["text"]), delay=70)
        time.sleep(0.4)
    if "press" in step:
        page.keyboard.press(step["press"])
        time.sleep(0.5)
    if "scroll" in step:
        n = int(step["scroll"])
        sign = 1 if n >= 0 else -1
        for _ in range(abs(n) // 40):
            page.mouse.wheel(0, 40 * sign)
            time.sleep(0.02)
        time.sleep(0.3)
    if "wait" in step:
        time.sleep(float(step["wait"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--tts", choices=["edge", "silent"], default="edge")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--setup", action="store_true", help="screen mode: open browser once to log in to sites")
    ap.add_argument("--out")
    args = ap.parse_args()

    spath = Path(args.script).resolve()
    base = spath.parent
    cfg = json.loads(spath.read_text(encoding="utf-8"))
    W, H = cfg.get("viewport", [1920, 1080])
    voice = cfg.get("voice", "en-IN-PrabhatNeural")
    rate = cfg.get("rate", "+0%")
    out = Path(args.out or cfg.get("out", spath.stem + ".mp4"))
    if not out.is_absolute():
        out = base / out
    steps = cfg["steps"]

    tmp = Path(tempfile.mkdtemp(prefix="demorec_"))
    # 1) narration audio first, so durations are known
    for i, s in enumerate(steps):
        s["_audio"], s["_dur"] = None, 0.0
        if s.get("audio"):
            p = (base / s["audio"]).resolve()
        elif s.get("say"):
            p = tmp / ("say_%03d.mp3" % i)
            make_audio(s["say"], voice, rate, p, args.tts)
        else:
            continue
        s["_audio"], s["_dur"] = p, audio_len(p)
    print("narration ready:", sum(1 for s in steps if s["_audio"]), "clips")

    # 2) record
    from playwright.sync_api import sync_playwright
    clips, timeline, caps = [], [], []
    screen = cfg.get("mode", "browser") == "screen"
    with sync_playwright() as pw:
        cap = None
        if screen:
            # real Chrome with a saved profile (logins persist), whole desktop captured by ffmpeg
            prof = str((base / cfg.get("profile", ".demo_profile")).resolve())
            kw = dict(headless=False, no_viewport=True, args=["--start-maximized"],
                      ignore_default_args=["--enable-automation"])
            try:
                ctx = pw.chromium.launch_persistent_context(prof, channel="chrome", **kw)
            except Exception:
                ctx = pw.chromium.launch_persistent_context(prof, **kw)
            browser = None
            if args.setup:
                ctx.pages[0].goto(cfg.get("setup_url", "https://web.whatsapp.com"))
                input("Browser me sab sites pe login karo (WhatsApp, Google...). Ho jaye to yaha Enter dabao: ")
                ctx.close()
                print("Login saved in", prof)
                return
        else:
            browser = pw.chromium.launch(headless=not args.headed)
            ctx = browser.new_context(viewport={"width": W, "height": H},
                                      record_video_dir=str(tmp / "vid"),
                                      record_video_size={"width": W, "height": H})
        ctx.add_init_script(CURSOR_JS)
        page = ctx.pages[0] if (screen and ctx.pages) else ctx.new_page()
        tabs = {"main": page}
        lead = 0.0
        if screen:
            vpath = tmp / "screen.mp4"
            if sys.platform.startswith("win"):
                src = ["-f", "gdigrab", "-framerate", "25", "-draw_mouse", "1", "-i", "desktop"]
            elif sys.platform == "darwin":
                src = ["-f", "avfoundation", "-framerate", "25", "-capture_cursor", "1", "-i", "1:none"]
            else:
                src = ["-f", "x11grab", "-framerate", "25", "-i", os.environ.get("DISPLAY", ":0")]
            time.sleep(1.0)  # let the browser window settle
            r0 = time.monotonic()
            cap = subprocess.Popen([FF, "-y"] + src + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                                    "-pix_fmt", "yuv420p", str(vpath)],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.5)
            if cap.poll() is not None:
                raise RuntimeError("screen capture did not start (ffmpeg exited)")
            lead = time.monotonic() - r0
        t0 = time.monotonic()
        time.sleep(0.5)
        for i, s in enumerate(steps):
            start = time.monotonic() - t0
            delay = float(s.get("say_delay", 0.3))
            if s["_audio"]:
                a0 = max(0.0, start + lead + delay + float(cfg.get("audio_offset", 0)))
                clips.append((s["_audio"], a0))
                if s.get("say") and cfg.get("captions", True):
                    caps.append((a0, a0 + s["_dur"], s["say"]))
            if "tab" in s:
                if s["tab"] not in tabs:
                    tabs[s["tab"]] = ctx.new_page()
                page = tabs[s["tab"]]
                page.bring_to_front()
                time.sleep(0.6)
            do_actions(page, s, base)
            need = (delay + s["_dur"] + float(s.get("pad", 0.6))) if s["_audio"] else float(s.get("hold", 0))
            left = start + need - (time.monotonic() - t0)
            if left > 0:
                time.sleep(left)
            timeline.append({"step": i, "start": round(start, 2), "end": round(time.monotonic() - t0, 2)})
            print("step %d done  %.1fs -> %.1fs" % (i, start, timeline[-1]["end"]))
        time.sleep(1.0)
        if screen:
            try:
                cap.stdin.write(b"q")
                cap.stdin.flush()
            except Exception:
                pass
            cap.wait(timeout=30)
            ctx.close()
        else:
            vpath = page.video.path()
            ctx.close()
            browser.close()

    # 3) mix narration + burn captions
    out.parent.mkdir(parents=True, exist_ok=True)
    srt = out.with_suffix(".srt")
    if caps:
        srt.write_text("\n".join("%d\n%s --> %s\n%s\n" % (n + 1, srt_time(a), srt_time(b), t)
                                 for n, (a, b, t) in enumerate(caps)), encoding="utf-8")
        make_ass(caps, W, H, tmp / "caps.ass", int(cfg.get("caption_size", H * 0.045)))

    def build(burn):
        cmd = [FF, "-y", "-i", str(vpath)]
        if clips:
            for c, _ in clips:
                cmd += ["-i", str(c)]
            parts = ["[%d:a]adelay=%d:all=1[a%d]" % (k + 1, int(off * 1000), k) for k, (_, off) in enumerate(clips)]
            mix = "".join("[a%d]" % k for k in range(len(clips)))
            parts.append("%samix=inputs=%d:normalize=0:dropout_transition=0,apad[aout]" % (mix, len(clips)))
            cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[aout]",
                    "-c:a", "aac", "-b:a", "160k"]
        if burn:
            cmd += ["-vf", "subtitles=caps.ass"]  # relative name; ffmpeg runs inside tmp (avoids Windows path escaping)
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "23",
                "-shortest", str(out)]
        return cmd

    try:
        run(build(bool(caps)), cwd=str(tmp))
    except RuntimeError as e:
        if not caps:
            raise
        print("WARNING: caption burn failed, making video without burned captions (.srt still saved).\n", str(e)[-400:])
        run(build(False), cwd=str(tmp))
    (out.with_suffix(".timeline.json")).write_text(json.dumps(timeline, indent=1), encoding="utf-8")
    print("DONE ->", out)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)
