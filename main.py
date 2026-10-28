import argparse
import json
import math
import re
import time
import traceback
import threading
import queue
from pathlib import Path

import cv2
import numpy as np
import pygame
from pygame.math import Vector2

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    print("[WARNING] pyserial tidak terinstal. Mode Wayang Fisik tidak tersedia.")

from rigmath import solve_arm, arm_target_from_hand

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
AUDIO = ROOT / "audio"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
STORY = json.loads((ROOT / "story.json").read_text(encoding="utf-8"))

BG_FILES = {
    # Background khusus antarmuka utama, Quiz, dan Gesture Attack.
    # Story tetap memakai background ceritanya sendiri.
    "ui_edalang": "bg_edalang_ui.jpg",
    # Background batik krem untuk Menu Utama dan Gesture Attack (Quiz tetap memakai ui_edalang).
    "ui_batik": "bg_batik_ui.jpg",
    # Background mode Story sesuai empat foto yang dikirim pengguna.
    "hutan_sore": "story_hutan.jpg",
    "persimpangan": "story_persimpangan.jpg",
    "jejak_kaki": "story_jejak.jpg",
    "keluar_hutan": "story_keluar.jpg",
}

# Teks pembukaan HARUS sama persis dengan rekaman 01_pembukaan.mp3.
# Jangan memakai teks narasi adegan 1 di bagian pembukaan karena audionya berbeda.
OPENING_PAGES = [
    "Di sebuah hutan yang jauh dari keramaian, dua kesatria sedang menempuh perjalanan panjang.",
    "Bima dan Arjuna berjalan bersama, melewati pepohonan yang lebat dan jalan setapak yang sunyi.",
    "Namun, perjalanan mereka tidak selalu berjalan mudah. Di tengah hutan, mereka harus menghadapi sebuah pilihan yang menguji kesabaran, keyakinan, dan hubungan di antara mereka.",
    "Akankah mereka mampu menemukan jalan yang benar?",
    "Dan mampukah mereka tetap saling percaya, meskipun memiliki pendapat yang berbeda?",
]

# Batas subtitle pembukaan berdasarkan jeda suara 01_pembukaan.mp3.
# Angka ini mencegah subtitle tertinggal karena pembagian hanya berdasarkan jumlah kata.
OPENING_TIMINGS = [
    (0.00, 6.54),
    (6.54, 14.16),
    (14.16, 21.98),
    (21.98, 27.45),
    (27.45, 33.64),
]

# Timestamp subtitle narasi berdasarkan jeda aktual tiap rekaman.
# Subtitle mulai dari awal suara supaya tidak terasa terlambat.
NARRATION_TIMINGS = {
    "07_adegan1.mp3": [(0.00, 6.05), (6.05, 11.55)],
    "08_adegan2.mp3": [(0.00, 4.79), (4.79, 8.69), (8.69, 13.53), (13.53, 17.21)],
    "09_adegan3.mp3": [(0.00, 5.10), (5.10, 9.61), (9.61, 15.15), (15.15, 20.19)],
    "10_adegan4.mp3": [(0.00, 5.89), (5.89, 11.00), (11.00, 14.79), (14.79, 22.81), (22.81, 29.52)],
    "11_adegan5.mp3": [(0.00, 7.11), (7.11, 14.45), (14.45, 22.77), (22.77, 34.27)],
    "12_akhir_cerita.mp3": [(0.00, 7.11), (7.11, 14.45), (14.45, 22.77), (22.77, 34.27)],
    "13_pesan_moral.mp3": [(0.00, 5.61), (5.61, 10.38), (10.38, 15.88)],
    "14_penutup.mp3": [(0.00, 4.69), (4.69, 7.59), (7.59, 12.38)],
}
AFTER_PAUSE_TEXT = "Kisah ini membawa kita pada sebuah perjalanan sederhana, tetapi menyimpan pelajaran tentang persahabatan dan kebersamaan."
FINAL_STORY_TEXT = (
    "Bima dan Arjuna akhirnya melanjutkan perjalanan melalui jalan yang telah mereka pilih bersama. "
    "Dari perjalanan tersebut, mereka belajar bahwa perbedaan pendapat bukanlah alasan untuk bertengkar. "
    "Dengan keberanian, kebijaksanaan, dan kerja sama, mereka dapat menghadapi berbagai kesulitan. "
    "Bima dan Arjuna kemudian melanjutkan perjalanan dengan hati yang tenang, sambil menjaga janji untuk selalu saling menghargai dan membantu."
)
MORAL_TEXT = (
    "Dari kisah Bima dan Arjuna, kita belajar bahwa perbedaan pendapat bukanlah alasan untuk saling bermusuhan. "
    "Dengan saling mendengarkan, menghargai, dan bekerja sama, setiap masalah dapat dihadapi dengan lebih baik."
)
CLOSING_TEXT = (
    "Demikianlah kisah perjalanan Bima dan Arjuna. Semoga kisah ini mengingatkan kita untuk selalu menjaga persahabatan dan menghargai satu sama lain."
)
ENDING_TEXT = "Perbedaan bukanlah penghalang untuk tetap bersama."

QUIZ_QUESTIONS = [
    {
        "question": "Mengapa Bima dan Arjuna berhenti di persimpangan?",
        "options": ["Mencari makanan", "Menentukan jalan yang benar", "Mencari rumah", "Menunggu hujan"],
        "answer": 1,
        "explanation": "Mereka berhenti karena harus menentukan jalan yang tepat untuk melanjutkan perjalanan.",
    },
    {
        "question": "Jalan mana yang awalnya dipilih Bima?",
        "options": ["Jalan kanan", "Jalan tengah", "Jalan kiri", "Jalan belakang"],
        "answer": 2,
        "explanation": "Bima awalnya memilih jalan kiri sebelum mereka mencari petunjuk lebih lanjut.",
    },
    {
        "question": "Apa yang dilakukan Bima dan Arjuna untuk menentukan jalan?",
        "options": ["Bertengkar", "Mencari petunjuk bersama", "Berpisah", "Menunggu orang lain"],
        "answer": 1,
        "explanation": "Keduanya mencari petunjuk bersama agar dapat menentukan arah perjalanan dengan bijak.",
    },
    {
        "question": "Petunjuk apa yang mereka temukan?",
        "options": ["Peta", "Jejak kaki", "Kompas", "Jembatan"],
        "answer": 1,
        "explanation": "Jejak kaki menjadi petunjuk yang membantu mereka memilih arah di persimpangan.",
    },
    {
        "question": "Apa pesan utama dari kisah Bima dan Arjuna?",
        "options": ["Selalu mengikuti pendapat sendiri", "Perbedaan harus dihindari", "Saling menghargai dan bekerja sama", "Jangan bepergian ke hutan"],
        "answer": 2,
        "explanation": "Kisah ini menekankan pentingnya saling menghargai, bekerja sama, dan mengambil keputusan bersama.",
    },
]


def safe_sound_file(name):
    p = AUDIO / name
    return p if p.exists() else None


def validate_story_assets():
    """Validate the complete story before the first frame is shown.

    This prevents a missing asset from silently shortening the story and
    makes the terminal show exactly what will be played.
    """
    errors = []

    if not STORY.get("scenes"):
        errors.append("story.json tidak memiliki scenes.")

    for scene in STORY.get("scenes", []):
        sid = scene.get("id", "?")
        narration = scene.get("narration")
        if not narration or safe_sound_file(narration) is None:
            errors.append(f"Adegan {sid}: audio narasi tidak ditemukan: {narration}")

        dialogues = scene.get("dialogues", [])
        for idx, item in enumerate(dialogues, 1):
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                errors.append(f"Adegan {sid} dialog {idx}: format harus [speaker, text, audio].")
                continue
            speaker, text, audio_name = item
            if not str(speaker).strip() or not str(text).strip():
                errors.append(f"Adegan {sid} dialog {idx}: speaker/teks kosong.")
            if safe_sound_file(audio_name) is None:
                errors.append(f"Adegan {sid} dialog {idx}: audio tidak ditemukan: {audio_name}")

        if scene.get("background") not in BG_FILES:
            errors.append(f"Adegan {sid}: background tidak dikenal: {scene.get('background')}")

    intro_audio = [
        "01_pembukaan.mp3", "02_setelah_jeda.mp3", "04_mari_kita_ikuti.mp3",
        "05_judul_subjudul.mp3", "06_judul_utama.mp3",
        "12_akhir_cerita.mp3", "13_pesan_moral.mp3", "14_penutup.mp3",
    ]
    for name in intro_audio:
        if safe_sound_file(name) is None:
            errors.append(f"Audio utama tidak ditemukan: {name}")

    if errors:
        print("\n[ERROR] Validasi aset gagal:")
        for err in errors:
            print("  -", err)
        raise RuntimeError("Ada aset/format cerita yang tidak valid. Perbaiki daftar di atas.")

    print("[CHECK] Semua audio, dialog, dan background ditemukan.")
    print("[CHECK] Urutan cerita:")
    for scene in STORY["scenes"]:
        print(f"  Adegan {scene['id']}: narasi -> {len(scene['dialogues'])} dialog")


class Puppet:
    def __init__(self, filename, x, y, target_height, ox, oy):
        path = ASSETS / filename
        if not path.exists():
            raise FileNotFoundError(f"File wayang tidak ditemukan: {path}")
        original = pygame.image.load(str(path)).convert_alpha()
        bbox = original.get_bounding_rect(min_alpha=8)
        if bbox.width > 2 and bbox.height > 2:
            original = original.subsurface(bbox).copy()
        ratio = target_height / max(1, original.get_height())
        self.base = pygame.transform.smoothscale(
            original,
            (max(1, int(original.get_width() * ratio)), max(1, int(original.get_height() * ratio))),
        )
        self.image = self.base
        self.pos = Vector2(x, y)
        self.target = self.pos.copy()
        self.offset = Vector2(ox, oy)
        # Arah hadap asli gambar sumber: +1 = menghadap kanan, -1 = kiri.
        self.source_facing = 1
        self.facing = 1

    def set_facing(self, direction):
        """Set arah hadap visual secara langsung (+1 kanan, -1 kiri)."""
        direction = -1 if direction < 0 else 1
        if direction != self.facing:
            self.facing = direction
            self.image = pygame.transform.flip(self.base, True, False) if direction < 0 else self.base

    def set_visual_facing(self, direction, source_facing=None):
        """Set arah visual dengan memperhitungkan orientasi asli aset."""
        direction = -1 if direction < 0 else 1
        if source_facing is not None:
            self.source_facing = -1 if source_facing < 0 else 1
        # Jika arah sumber sama dengan arah yang diinginkan, gunakan gambar asli.
        # Jika berbeda, mirror secara horizontal.
        needs_flip = self.source_facing != direction
        self.facing = direction
        self.image = pygame.transform.flip(self.base, True, False) if needs_flip else self.base

    def update(self, palm, smooth):
        if palm is not None:
            self.target = Vector2(palm) + self.offset
        self.pos += (self.target - self.pos) * smooth

    def update_hand(self, hand, smooth):
        """Wayang statis: hanya mengikuti telapak tangan."""
        self.update(hand["palm"], smooth)

    def draw(self, screen):
        rect = self.image.get_rect(center=(round(self.pos.x), round(self.pos.y)))
        try:
            mask = pygame.mask.from_surface(self.image, 8)
            halo = mask.to_surface(setcolor=(*HALO_COLORS[STYLE["halo"]], 255), unsetcolor=(0, 0, 0, 0))
            halo.set_colorkey((0, 0, 0, 0))
            for dx, dy in ((-3,0),(3,0),(0,-3),(0,3),(-2,-2),(2,-2),(-2,2),(2,2)):
                screen.blit(halo, (rect.x + dx, rect.y + dy))
        except Exception:
            pass
        screen.blit(self.image, rect)

    def draw_at(self, screen, center, scale=1.0):
        scale = max(0.05, scale)
        img = pygame.transform.smoothscale(
            self.image,
            (max(1, int(self.image.get_width() * scale)), max(1, int(self.image.get_height() * scale)),),
        )
        screen.blit(img, img.get_rect(center=(round(center[0]), round(center[1]))))


# Warna garis tepi (halo) wayang: "gold" untuk latar gelap, "dark" untuk latar krem/terang.
STYLE = {"halo": "gold"}
HALO_COLORS = {"gold": (238, 196, 105), "dark": (66, 38, 20)}


def _blit_rot(dest, img, pivot, at, ccw_deg):
    """Gambar img diputar ccw_deg (berlawanan jarum jam) mengelilingi titik pivot, pivot diletakkan di 'at'."""
    w, h = img.get_size()
    rot = pygame.transform.rotate(img, ccw_deg)
    v = Vector2(pivot[0] - w / 2, pivot[1] - h / 2).rotate(-ccw_deg)
    dest.blit(rot, rot.get_rect(center=(round(at[0] - v.x), round(at[1] - v.y))))


def _make_halo(img, pad=5, color=(238, 196, 105)):
    w, h = img.get_size()
    sil = pygame.mask.from_surface(img, 8).to_surface(setcolor=(*color, 255), unsetcolor=(0, 0, 0, 0))
    out = pygame.Surface((w + 2 * pad, h + 2 * pad), pygame.SRCALPHA)
    for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)):
        out.blit(sil, (pad + dx, pad + dy))
    return out


class RiggedPuppet:
    """Wayang berartikulasi: badan + lengan depan (atas & bawah) dengan IK.
    Badan mengikuti telapak tangan (miring/berayun), lengan mengikuti arah jari.
    Bagian-bagian dibuat oleh tools/make_rig.py ke assets/rig/<nama>/."""
    PAD = 5

    def __init__(self, filename, x, y, target_height, ox, oy):
        stem = Path(filename).stem
        rdir = ASSETS / "rig" / stem
        rig = json.loads((rdir / "rig.json").read_text(encoding="utf-8"))
        self.cfg = CONFIG.get("rig", {})
        raw = {k: pygame.image.load(str(rdir / f"{k}.png")).convert_alpha() for k in ("body", "upper", "fore")}
        s = target_height / max(1, raw["body"].get_height())
        self.s = s
        sc = lambda im: pygame.transform.smoothscale(im, (max(1, int(im.get_width() * s)), max(1, int(im.get_height() * s))))
        self.body, self.upper, self.fore = sc(raw["body"]), sc(raw["upper"]), sc(raw["fore"])
        self.halo_sets = {k: tuple(_make_halo(i, self.PAD, c) for i in (self.body, self.upper, self.fore))
                          for k, c in HALO_COLORS.items()}
        self.up_pivot = Vector2(rig["upper"]["pivot"]) * s
        self.fo_pivot = Vector2(rig["fore"]["pivot"]) * s
        self.shoulder = Vector2(rig["shoulder_on_body"]) * s
        self.lu, self.lf = rig["len_upper"] * s, rig["len_fore"] * s
        self.rest_u = math.radians(rig["rest_upper_angle"])
        self.rest_f = math.radians(rig["rest_fore_angle"])
        hand_rest = Vector2(rig["shoulder_on_body"]) + (Vector2(rig["fore"]["hand_local"]) - Vector2(rig["fore"]["pivot"])) \
            + (Vector2(rig["upper"]["elbow_local"]) - Vector2(rig["upper"]["pivot"]))
        self.rest_vec = (hand_rest - Vector2(rig["shoulder_on_body"])) * s
        self.rod_anchor = Vector2(rig.get("rod_anchor", [rig["body_size"][0] * 0.5, rig["body_size"][1] * 0.42])) * s
        self.M = int((self.lu + self.lf) * 1.08) + self.PAD + 4
        self.body_rod = bool(rig.get("body_rod", True))
        self.pos = Vector2(x, y)
        self.target = self.pos.copy()
        self.offset = Vector2(ox, oy)
        self.source_facing = int(rig.get("source_facing", -1))
        self.facing = 1
        self.flip = False
        self.arm_vec = Vector2(self.rest_vec)
        self.arm_goal = Vector2(self.rest_vec)
        self.hand_ttl = 0
        self.tilt = 0.0
        self.tilt_goal = 0.0
        self.prev_x = self.pos.x
        self.image = self.body  # kompatibilitas

    # --- arah hadap (sama dengan Puppet) ---
    def set_facing(self, direction):
        direction = -1 if direction < 0 else 1
        self.facing = direction
        self.flip = direction < 0

    def set_visual_facing(self, direction, source_facing=None):
        direction = -1 if direction < 0 else 1
        if source_facing is not None:
            self.source_facing = -1 if source_facing < 0 else 1
        self.facing = direction
        self.flip = self.source_facing != direction

    # --- input ---
    def update(self, palm, smooth):
        if palm is not None:
            self.target = Vector2(palm) + self.offset
        self.pos += (self.target - self.pos) * smooth

    def update_hand(self, hand, smooth):
        self.update(hand["palm"], smooth)
        self.hand_ttl = 10
        wrist = hand.get("wrist")
        size = hand.get("size", 0) or 0
        if wrist is None or size <= 1:
            return
        mode = self.cfg.get("arm_driver", "thumb")
        key, lo, hi = ("thumb", 0.85, 1.35) if mode == "thumb" else ("tip", 1.35, 2.0)
        pt = hand.get(key)
        if pt is None:
            return
        v = (Vector2(pt) - Vector2(wrist)) / size
        tgt = arm_target_from_hand((v.x, v.y), self.flip, self.lu, self.lf, lo, hi)
        if tgt is not None:
            self.arm_goal = Vector2(tgt)
        # kemiringan badan dari rotasi tangan (telapak tegak = 0)
        palm = Vector2(hand["palm"])
        r = palm - Vector2(wrist)
        roll = math.degrees(math.atan2(r.x, -r.y)) if r.length() > 1 else 0.0
        self.tilt_goal = max(-12.0, min(12.0, -roll * float(self.cfg.get("roll_gain", 0.35))))

    # --- gambar ---
    def _frame(self):
        cfg = self.cfg
        t = pygame.time.get_ticks() / 1000.0
        if self.hand_ttl > 0:
            self.hand_ttl -= 1
            goal = self.arm_goal
            tilt_goal = self.tilt_goal
        else:
            goal = Vector2(self.rest_vec)
            tilt_goal = 0.0
        a = float(cfg.get("arm_smooth", 0.35))
        self.arm_vec += (goal - self.arm_vec) * a
        # ayunan karena kecepatan gerak + napas pelan
        vel = self.pos.x - self.prev_x
        self.prev_x = self.pos.x
        sway = max(-8.0, min(8.0, -vel * float(cfg.get("sway_gain", 0.25))))
        self.tilt += (tilt_goal + sway - self.tilt) * 0.25
        tilt = self.tilt + math.sin(t * 1.7) * 0.8

        M = self.M
        bw, bh = self.body.get_size()
        canvas = pygame.Surface((bw + 2 * M, bh + 2 * M), pygame.SRCALPHA)
        S = self.shoulder + Vector2(M, M)
        th_u, th_f, E, Hd = solve_arm((self.arm_vec.x, self.arm_vec.y), self.lu, self.lf)
        Ep, Hp = S + Vector2(E), S + Vector2(Hd)
        du = -math.degrees(th_u - self.rest_u)
        df = -math.degrees(th_f - self.rest_f)
        P = self.PAD
        body_halo, upper_halo, fore_halo = self.halo_sets[STYLE["halo"]]
        canvas.blit(body_halo, (M - P, M - P))
        _blit_rot(canvas, fore_halo, self.fo_pivot + Vector2(P, P), Ep, df)
        _blit_rot(canvas, upper_halo, self.up_pivot + Vector2(P, P), S, du)
        canvas.blit(self.body, (M, M))
        _blit_rot(canvas, self.fore, self.fo_pivot, Ep, df)
        _blit_rot(canvas, self.upper, self.up_pivot, S, du)

        img = pygame.transform.rotate(canvas, tilt)
        if self.flip:
            img = pygame.transform.flip(img, True, False)
        center = Vector2(canvas.get_width() / 2, canvas.get_height() / 2)

        def to_screen_vec(p):
            v = (Vector2(p) - center).rotate(-tilt)
            if self.flip:
                v.x = -v.x
            return v
        return img, to_screen_vec(Hp), to_screen_vec(self.rod_anchor + Vector2(M, M))

    def _rod(self, screen, start, end, width):
        pygame.draw.line(screen, (38, 24, 16), start, end, width + 2)
        pygame.draw.line(screen, (96, 64, 38), start, end, max(1, width - 1))

    def draw(self, screen):
        img, hand_v, rod_v = self._frame()
        c = (round(self.pos.x), round(self.pos.y))
        H = screen.get_height()
        rods = bool(self.cfg.get("rods", True))
        if rods and self.body_rod:  # gapit badan di belakang wayang
            a = Vector2(c) + rod_v
            self._rod(screen, a, (a.x - 10 * (1 if not self.flip else -1), H + 20), max(4, int(self.s * 22)))
        screen.blit(img, img.get_rect(center=c))
        if rods:  # tuding/gapit tangan
            h = Vector2(c) + hand_v
            self._rod(screen, h, (h.x + (14 if not self.flip else -14), H + 20), max(3, int(self.s * 15)))

    def draw_at(self, screen, center, scale=1.0):
        scale = max(0.05, scale)
        img, _, _ = self._frame()
        img = pygame.transform.smoothscale(img, (max(1, int(img.get_width() * scale)), max(1, int(img.get_height() * scale))))
        screen.blit(img, img.get_rect(center=(round(center[0]), round(center[1]))))


def make_puppet(filename, x, y, target_height, ox, oy):
    """Pakai wayang berartikulasi jika rig tersedia, jika tidak pakai wayang statis."""
    stem = Path(filename).stem
    if CONFIG.get("rig", {}).get("enabled", True) and (ASSETS / "rig" / stem / "rig.json").exists():
        try:
            return RiggedPuppet(filename, x, y, target_height, ox, oy)
        except Exception as exc:
            print(f"[WARNING] Rig {stem} gagal dimuat ({exc}); memakai wayang statis.")
    return Puppet(filename, x, y, target_height, ox, oy)


# ---------------------------------------------------------------------------
# Tampilan responsif: semua digambar ke kanvas logis W x H (mis. 1280x720),
# lalu diskalakan ke jendela/fullscreen dengan menjaga rasio (letterbox).
# Posisi mouse dikonversi balik ke koordinat kanvas.
# ---------------------------------------------------------------------------
_VIEW = {"scale": 1.0, "ox": 0, "oy": 0}


def present_canvas(canvas):
    window = pygame.display.get_surface()
    ww, wh = window.get_size()
    cw, ch = canvas.get_size()
    sc = min(ww / cw, wh / ch)
    nw, nh = max(1, int(cw * sc)), max(1, int(ch * sc))
    ox, oy = (ww - nw) // 2, (wh - nh) // 2
    _VIEW.update(scale=sc, ox=ox, oy=oy)
    window.fill((0, 0, 0))
    if (nw, nh) == (cw, ch):
        window.blit(canvas, (ox, oy))
    else:
        window.blit(pygame.transform.smoothscale(canvas, (nw, nh)), (ox, oy))
    pygame.display.flip()


def logical_pos(pos):
    """Konversi posisi mouse jendela -> koordinat kanvas logis."""
    sc = _VIEW["scale"] or 1.0
    return (int((pos[0] - _VIEW["ox"]) / sc), int((pos[1] - _VIEW["oy"]) / sc))


def logical_mouse():
    return logical_pos(pygame.mouse.get_pos())


def load_backgrounds(size):
    W, H = size
    result = {}
    for key, filename in BG_FILES.items():
        path = ASSETS / filename
        if not path.exists():
            print(f"[WARNING] Background tidak ditemukan: {path}")
            continue
        img = pygame.image.load(str(path)).convert()
        iw, ih = img.get_size()
        scale = max(W / iw, H / ih)
        nw, nh = max(W, int(iw * scale)), max(H, int(ih * scale))
        img = pygame.transform.smoothscale(img, (nw, nh))
        x = (nw - W) // 2
        y = (nh - H) // 2
        result[key] = img.subsurface(pygame.Rect(x, y, W, H)).copy()
    return result


def draw_background(screen, backgrounds, key, W, H):
    bg = backgrounds.get(key)
    if bg is None:
        screen.fill((25, 25, 25))
    else:
        screen.blit(bg, (0, 0))


def gesture_state(hand):
    lm = hand.landmark
    wrist = np.array([lm[0].x, lm[0].y], np.float32)
    palm_points = np.array([[lm[i].x, lm[i].y] for i in (5, 9, 13, 17)], np.float32)
    palm_size = max(float(np.mean(np.linalg.norm(palm_points - wrist, axis=1))), 1e-4)
    pairs = [(8, 6), (12, 10), (16, 14), (20, 18)]
    extended = 0
    folded = 0
    for tip, pip in pairs:
        dt = np.linalg.norm(np.array([lm[tip].x, lm[tip].y]) - wrist) / palm_size
        dp = np.linalg.norm(np.array([lm[pip].x, lm[pip].y]) - wrist) / palm_size
        if dt > dp * 1.12 and dt > 1.25:
            extended += 1
        elif dt < dp * 1.05:
            folded += 1
    if extended >= 4:
        return 1
    if folded >= 4:
        return -1
    return 0


class GestureStabilizer:
    def __init__(self, required_frames=6):
        self.required_frames = required_frames
        self.candidate = 0
        self.count = 0
        self.stable = 1

    def update(self, state):
        if state == 0:
            self.candidate = 0
            self.count = 0
            return self.stable
        if state == self.stable:
            self.candidate = 0
            self.count = 0
            return self.stable
        if state == self.candidate:
            self.count += 1
        else:
            self.candidate = state
            self.count = 1
        if self.count >= self.required_frames:
            self.stable = state
            self.candidate = 0
            self.count = 0
        return self.stable


def _hand_info(hand, W, H):
    lm = hand.landmark
    pt = lambda i: Vector2(lm[i].x * W, lm[i].y * H)
    wrist, palm = pt(0), pt(9)
    return {
        "palm": palm,
        "gesture": gesture_state(hand),
        "wrist": wrist,
        "tip": pt(8),
        "thumb": pt(4),
        "size": max(wrist.distance_to(palm), 1.0),
    }


def detect_hands(result, W, H):
    found = {}
    if not result.multi_hand_landmarks:
        return found
    infos = [_hand_info(h, W, H) for h in result.multi_hand_landmarks]
    for i, info in enumerate(infos):
        label = None
        if result.multi_handedness and i < len(result.multi_handedness):
            label = result.multi_handedness[i].classification[0].label
        if label:
            found[label] = info
    if not found:
        infos = sorted(infos, key=lambda x: x["palm"].x)
        if len(infos) == 1:
            found["Unknown"] = infos[0]
        elif len(infos) >= 2:
            found["Right"] = infos[0]
            found["Left"] = infos[-1]
    return found


def make_camera_preview(frame, result=None, preview_size=(430, 322)):
    """Create a mirrored live-camera preview with optional MediaPipe landmarks."""
    if frame is None:
        return None
    try:
        preview = frame.copy()
        if result is not None and getattr(result, "multi_hand_landmarks", None):
            h, w = preview.shape[:2]
            connections = [
                (0,1),(1,2),(2,3),(3,4),
                (0,5),(5,6),(6,7),(7,8),
                (5,9),(9,10),(10,11),(11,12),
                (9,13),(13,14),(14,15),(15,16),
                (13,17),(17,18),(18,19),(19,20),(0,17)
            ]
            for hand in result.multi_hand_landmarks:
                pts = []
                for lm in hand.landmark:
                    pts.append((int(lm.x * w), int(lm.y * h)))
                for a, b in connections:
                    cv2.line(preview, pts[a], pts[b], (50, 235, 80), 2, cv2.LINE_AA)
                for x, y in pts:
                    cv2.circle(preview, (x, y), 4, (35, 255, 90), -1, cv2.LINE_AA)
                    cv2.circle(preview, (x, y), 5, (15, 55, 20), 1, cv2.LINE_AA)
        target_w, target_h = preview_size
        preview = cv2.resize(preview, (target_w, target_h), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        return pygame.image.frombuffer(rgb.tobytes(), (target_w, target_h), "RGB").convert()
    except Exception:
        return None



def make_camera_cv_preview(frame, result=None, target_size=(480, 360)):
    """Build the live POV as an OpenCV frame for a separate desktop window."""
    if frame is None:
        return None
    try:
        preview = frame.copy()
        if result is not None and getattr(result, "multi_hand_landmarks", None):
            h, w = preview.shape[:2]
            connections = [
                (0,1),(1,2),(2,3),(3,4),
                (0,5),(5,6),(6,7),(7,8),
                (5,9),(9,10),(10,11),(11,12),
                (9,13),(13,14),(14,15),(15,16),
                (13,17),(17,18),(18,19),(19,20),(0,17)
            ]
            for hand in result.multi_hand_landmarks:
                pts = [(int(lm.x*w), int(lm.y*h)) for lm in hand.landmark]
                for a,b in connections:
                    cv2.line(preview, pts[a], pts[b], (50,235,80), 2, cv2.LINE_AA)
                for x,y in pts:
                    cv2.circle(preview, (x,y), 4, (35,255,90), -1, cv2.LINE_AA)
                    cv2.circle(preview, (x,y), 5, (15,55,20), 1, cv2.LINE_AA)
        tw, th = target_size
        preview = cv2.resize(preview, (tw, th), interpolation=cv2.INTER_AREA)
        cv2.rectangle(preview, (0,0), (tw-1,th-1), (245,215,150), 3)
        cv2.rectangle(preview, (10,10), (230,48), (0,0,0), -1)
        cv2.putText(preview, "POV TANGAN - LIVE", (20,37),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255,245,210), 2, cv2.LINE_AA)
        cv2.rectangle(preview, (10, th-45), (tw-10, th-10), (0,0,0), -1)
        cv2.putText(preview, "Gerakkan tangan untuk mengendalikan wayang", (20, th-22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255,255,255), 1, cv2.LINE_AA)
        return preview
    except Exception:
        return None


def update_pov_window(frame, result, enabled):
    """Show POV in a separate desktop window so it never covers the story."""
    window_name = "POV Tangan - Live"
    if not enabled:
        try:
            cv2.destroyWindow(window_name)
        except Exception:
            pass
        return
    preview = make_camera_cv_preview(frame, result)
    if preview is None:
        return
    try:
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, 480, 360)
        cv2.imshow(window_name, preview)
        # Process the OpenCV window without waiting for input.
        cv2.waitKey(1)
    except Exception as exc:
        print(f"[WARNING] Jendela POV tidak dapat ditampilkan: {exc}")

def draw_pov_overlay(screen, camera_surface, W, H, pov_font, show_landmarks=True):
    """Draw a live POV/camera window without disturbing the story layer."""
    if camera_surface is None:
        return
    pw, ph = camera_surface.get_size()
    margin = 22
    x = W - pw - margin
    y = margin + 42

    # Shadow/backplate
    shadow = pygame.Surface((pw + 12, ph + 12), pygame.SRCALPHA)
    shadow.fill((0, 0, 0, 150))
    screen.blit(shadow, (x - 6, y - 6))

    # Camera image
    screen.blit(camera_surface, (x, y))

    # Border and title
    pygame.draw.rect(screen, (245, 215, 150), pygame.Rect(x, y, pw, ph), 3)
    label = pov_font.render("POV TANGAN • LIVE", True, (255, 245, 210))
    label_bg = pygame.Surface((label.get_width() + 18, label.get_height() + 8), pygame.SRCALPHA)
    label_bg.fill((0, 0, 0, 185))
    screen.blit(label_bg, (x + 8, y + 8))
    screen.blit(label, (x + 17, y + 12))

    info = "Gerakkan tangan untuk mengendalikan wayang"
    info_s = pygame.font.SysFont("Arial", 16).render(info, True, (255, 255, 255))
    info_bg = pygame.Surface((info_s.get_width() + 14, info_s.get_height() + 6), pygame.SRCALPHA)
    info_bg.fill((0, 0, 0, 160))
    screen.blit(info_bg, (x + 8, y + ph - info_s.get_height() - 12))
    screen.blit(info_s, (x + 15, y + ph - info_s.get_height() - 9))


class Audio:
    """Single authoritative voice channel.

    A story item is considered finished only after the actual Sound duration
    has elapsed AND the mixer channel is no longer busy. This prevents the
    next item from starting early or two voices from overlapping.
    """
    def __init__(self):
        self.channel = pygame.mixer.Channel(0)
        self.cache = {}
        self.current = None
        self.current_started = 0.0
        self.current_length = 0.0
        self.failed = False
        # Estimated speech window inside the audio. Many generated voices
        # contain a short silence at the beginning/end; using the full MP3
        # length makes subtitles visibly lag behind the spoken words.
        self.current_lead = 0.0
        self.current_tail = 0.0
        self.timings = {}

    def sound(self, filename):
        if filename not in self.cache:
            path = safe_sound_file(filename)
            if path is None:
                print(f"[ERROR] Audio tidak ditemukan: {filename}")
                return None
            try:
                sound = pygame.mixer.Sound(str(path))
                self.cache[filename] = sound
                self.timings[filename] = self._estimate_speech_window(sound)
            except Exception as exc:
                print(f"[ERROR] Gagal memuat audio {filename}: {exc}")
                return None
        return self.cache[filename]

    def _estimate_speech_window(self, sound):
        """Estimate non-silent speech bounds from the decoded Sound.

        This is deliberately conservative: it removes only obvious leading
        and trailing silence, so subtitles follow speech rather than the
        encoder padding of an MP3.
        """
        try:
            arr = pygame.sndarray.array(sound)
            if arr is None or arr.size == 0:
                return 0.0, 0.0
            a = np.asarray(arr)
            if a.ndim > 1:
                a = np.max(np.abs(a.astype(np.float32)), axis=1)
            else:
                a = np.abs(a.astype(np.float32))
            peak = float(np.max(a))
            if peak <= 1e-6:
                return 0.0, 0.0
            # About -34 dB from peak; enough to ignore encoder silence while
            # preserving soft consonants in normal generated speech.
            threshold = peak * 0.02
            active = np.flatnonzero(a > threshold)
            if active.size == 0:
                return 0.0, 0.0
            # sndarray's first axis is already the sample/time axis, even
            # for stereo arrays, so no channel division is needed here.
            freq = max(1, int(pygame.mixer.get_init()[0]))
            first = float(active[0]) / freq
            last = float(active[-1] + 1) / freq
            length = float(sound.get_length())
            # Clamp: never remove more than 0.35 s from either side.
            lead = max(0.0, min(0.35, first))
            tail = max(0.0, min(0.45, length - last))
            return lead, tail
        except Exception:
            return 0.0, 0.0

    def preload_all(self):
        """Load every story voice before the first frame is played.

        Loading an MP3 for the first time during a transition can introduce a
        small stall. Preloading removes that source of timing jitter and makes
        every story item start from the same state.
        """
        names = [
            "01_pembukaan.mp3", "02_setelah_jeda.mp3", "04_mari_kita_ikuti.mp3",
            "05_judul_subjudul.mp3", "06_judul_utama.mp3",
            "12_akhir_cerita.mp3", "13_pesan_moral.mp3", "14_penutup.mp3",
        ]
        for scene in STORY.get("scenes", []):
            names.append(scene.get("narration"))
            for item in scene.get("dialogues", []):
                if isinstance(item, (list, tuple)) and len(item) == 3:
                    names.append(item[2])
        names = [n for n in names if n]
        for name in dict.fromkeys(names):
            sound = self.sound(name)
            if sound is None:
                raise RuntimeError(f"Audio gagal dipersiapkan: {name}")
        print(f"[CHECK] {len(dict.fromkeys(names))} file voice berhasil dipreload ke memori.")

    def play(self, filename):
        sound = self.sound(filename)
        self.channel.stop()
        self.current = filename
        self.current_length = float(sound.get_length()) if sound else 0.0
        self.failed = sound is None
        if sound is not None:
            self.channel.play(sound)
            # Timestamp and speech bounds belong to the same playback event.
            self.current_started = time.monotonic()
            self.current_lead, self.current_tail = self.timings.get(filename, (0.0, 0.0))
            print(f"[AUDIO] Mulai: {filename} ({self.current_length:.2f}s, lead={self.current_lead:.2f}s, tail={self.current_tail:.2f}s)")
            return True
        self.current_started = time.monotonic()
        return False

    def busy(self):
        if self.current is None:
            return False
        if self.failed:
            return False
        elapsed = time.monotonic() - self.current_started
        # Keep a tiny safety tail so the next voice cannot cut off the last
        # syllable because of mixer scheduling.
        return elapsed < self.current_length or self.channel.get_busy()

    def done(self, safety=0.12):
        if self.current is None:
            return True
        if self.failed:
            return True
        elapsed = time.monotonic() - self.current_started
        return elapsed >= self.current_length + safety and not self.channel.get_busy()

    def elapsed(self):
        return max(0.0, time.monotonic() - self.current_started)

    def progress(self):
        if self.current_length <= 0:
            return 1.0
        return max(0.0, min(1.0, self.elapsed() / self.current_length))

    def stop(self):
        self.channel.stop()
        self.current = None
        self.current_length = 0.0
        self.failed = False
        self.current_lead = 0.0
        self.current_tail = 0.0


class Flow:
    def __init__(self):
        self.phase = "menu"
        self.phase_started = time.monotonic()
        self.played = False
        self.scene_index = 0
        self.dialog_index = 0
        self.music_started = False
        self.menu_music_started = False
        self.title_started = 0.0
        self.opening_page = 0
        self.quiz_index = 0
        self.quiz_score = 0
        self.quiz_selected = None
        self.quiz_feedback_until = 0.0
        self.quiz_finished = False
        self.char_left_idx = 2  # Bima
        self.char_right_idx = 1 # Arjuna
        self.character_slot = 0
        self.menu_hover = None
        self.settings_show_pov = True
        self.settings_music = True

    def enter(self, phase):
        self.phase = phase
        self.phase_started = time.monotonic()
        self.played = False

    def elapsed(self):
        return time.monotonic() - self.phase_started


def wrap_text(font, text, max_width):
    lines = []
    current = ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if font.size(trial)[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def split_sentences(text):
    parts = [p.strip() for p in re.split(r'(?<=[.!?])\s+', (text or "").strip()) if p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def _speech_window(total_duration, lead=0.0, tail=0.0):
    total_duration = max(0.1, float(total_duration))
    lead = max(0.0, min(float(lead), total_duration * 0.25))
    tail = max(0.0, min(float(tail), total_duration * 0.25))
    start = min(lead, total_duration * 0.35)
    end = max(start + 0.15, total_duration - tail)
    if end > total_duration:
        end = total_duration
    return start, end


def _sentence_schedule(text, duration, lead=0.0, tail=0.0):
    """Return sentence timing slots weighted by word count.

    Narration is much easier to follow when one complete sentence is visible
    at a time. The previous build revealed every word across the entire
    paragraph, which made the text visibly trail the narrator. This schedule
    keeps sentence changes aligned to the voice while showing each sentence
    immediately when its spoken portion starts.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []
    start, end = _speech_window(duration, lead, tail)
    usable = max(0.2, end - start)
    weights = [max(1, len(re.findall(r"\S+", x))) for x in sentences]
    total = float(sum(weights))
    slots = []
    cursor = start
    for i, (sentence, weight) in enumerate(zip(sentences, weights)):
        if i == len(sentences) - 1:
            nxt = end
        else:
            nxt = cursor + usable * (weight / total)
        slots.append((sentence, cursor, max(cursor + 0.15, nxt)))
        cursor = nxt
    return slots


def narration_sentence_state(text, elapsed, total_duration, lead=0.0, tail=0.0, timings=None):
    sentences = split_sentences(text)
    if not sentences:
        return "", 0, 0.0

    if timings and len(timings) == len(sentences):
        # NARRATION_TIMINGS stores (start, end) pairs. Older builds expected
        # (sentence, start, end), which caused:
        #   ValueError: not enough values to unpack (expected 3, got 2)
        # Normalize both formats here so a bad timing table can never crash
        # the story playback.
        normalized = []
        for i, slot in enumerate(timings):
            try:
                if len(slot) == 2:
                    a, b = float(slot[0]), float(slot[1])
                    normalized.append((sentences[i], a, b))
                elif len(slot) == 3:
                    _, a, b = slot
                    normalized.append((sentences[i], float(a), float(b)))
                else:
                    raise ValueError
            except (TypeError, ValueError, IndexError):
                normalized = []
                break
        slots = normalized if len(normalized) == len(sentences) else None
    else:
        slots = None

    if not slots:
        # Fallback: jangan menunggu lead silence. Teks harus muncul saat
        # audio mulai diputar, lalu dibagi berdasarkan bobot kata.
        start = 0.0
        end = max(0.1, float(total_duration))
        usable = end - start
        weights = [max(1, len(re.findall(r"\S+", x))) for x in sentences]
        total = float(sum(weights))
        slots = []
        cursor = start
        for i, (sentence, weight) in enumerate(zip(sentences, weights)):
            nxt = end if i == len(sentences) - 1 else cursor + usable * (weight / total)
            slots.append((sentence, cursor, max(cursor + 0.15, nxt)))
            cursor = nxt

    t = max(0.0, float(elapsed))
    idx = len(slots) - 1
    # Keep the current sentence on screen for a short safety hold at each
    # manually supplied boundary. This prevents subtitles from moving to the
    # next sentence while the narrator is still finishing the previous one.
    boundary_hold = 0.22
    for i, (_, a, b) in enumerate(slots):
        switch_at = b + (boundary_hold if i < len(slots) - 1 else 0.0)
        if t < switch_at:
            idx = i
            break
    sentence, a, b = slots[idx]
    # Fade sangat singkat agar perpindahan halus tetapi tidak terasa terlambat.
    fade = 0.05
    local = max(0.0, t - a)
    alpha = int(min(255, 255 * local / fade)) if local < fade else 255
    return sentence, alpha, float(idx)


def draw_narration(screen, text, W, H, text_font, elapsed=0.0, total_duration=1.0,
                   title="Narator", lead=0.0, tail=0.0, timings=None):
    if not text:
        return
    visible_text, alpha, _ = narration_sentence_state(
        text, elapsed, total_duration, lead, tail, timings
    )
    if not visible_text:
        return

    panel_h = 190
    panel = pygame.Surface((W - 100, panel_h), pygame.SRCALPHA)
    panel_alpha = int(190 * max(0.82, alpha / 255))
    panel.fill((0, 0, 0, panel_alpha))
    screen.blit(panel, (50, H - panel_h - 25))

    label = pygame.font.SysFont("Arial", 28, bold=True).render(
        title, True, (255, 235, 170)
    )
    label.set_alpha(alpha)
    screen.blit(label, (80, H - panel_h - 8))

    y = H - panel_h + 36
    for line in wrap_text(text_font, visible_text, W - 160)[:4]:
        surf = text_font.render(line, True, (255, 255, 255))
        surf.set_alpha(alpha)
        screen.blit(surf, (80, y))
        y += 32


def dialogue_state(text, elapsed, lead=0.0, tail=0.0):
    """Display the complete dialogue smoothly without typewriter lag.

    The voice is the timing authority. Showing the whole sentence at the
    beginning avoids the old problem where the subtitle was still revealing
    characters while the speaker had already finished the sentence.
    """
    if not text:
        return "", 0
    # Tiny fade only; do not delay the subtitle behind the voice.
    local = max(0.0, float(elapsed) - max(0.0, float(lead)))
    fade = 0.08
    alpha = 255 if local >= fade else int(max(0.0, local / fade) * 255)
    return text, alpha


def draw_dialogue(screen, speaker, text, W, H, speaker_font, text_font,
                  elapsed=0.0, total_duration=1.0, lead=0.0, tail=0.0):
    panel_h = 155
    panel = pygame.Surface((W - 80, panel_h), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 190))
    screen.blit(panel, (40, H - panel_h - 24))
    speaker_surf = speaker_font.render(speaker, True, (255, 235, 170))
    screen.blit(speaker_surf, (65, H - panel_h - 5))
    visible_text, alpha = dialogue_state(text, elapsed)
    y = H - panel_h + 32
    for line in wrap_text(text_font, visible_text, W - 150)[:3]:
        surf = text_font.render(line, True, (255, 255, 255))
        surf.set_alpha(alpha)
        screen.blit(surf, (65, y))
        y += 30


def fade_overlay(screen, W, H, alpha):
    if alpha <= 0:
        return
    overlay = pygame.Surface((W, H))
    overlay.fill((0, 0, 0))
    overlay.set_alpha(int(max(0, min(255, alpha))))
    screen.blit(overlay, (0, 0))


def draw_title(screen, W, H, big_font, sub_font, progress):
    # progress 0..1: title gently appears while the image is fading darker.
    p = max(0.0, min(1.0, progress))
    alpha = int(255 * min(1.0, p * 1.35))
    scale = 0.88 + 0.12 * min(1.0, p * 1.15)
    title = big_font.render("BIMA DAN ARJUNA", True, (255, 245, 210))
    subtitle = sub_font.render("JANJI DI TENGAH HUTAN", True, (255, 245, 210))
    if scale != 1.0:
        title = pygame.transform.smoothscale(title, (int(title.get_width()*scale), int(title.get_height()*scale)))
        subtitle = pygame.transform.smoothscale(subtitle, (int(subtitle.get_width()*scale), int(subtitle.get_height()*scale)))
    title.set_alpha(alpha)
    subtitle.set_alpha(alpha)
    screen.blit(title, title.get_rect(center=(W//2, H//2 - 35)))
    screen.blit(subtitle, subtitle.get_rect(center=(W//2, H//2 + 38)))



# ---------------------------------------------------------------------------
# MENU / MODE SYSTEM
# ---------------------------------------------------------------------------
CHARACTERS = [
    # source_facing menunjukkan arah hadap asli file gambar.
    # Gesture Attack akan otomatis membuat karakter kiri menghadap kanan
    # dan karakter kanan menghadap kiri, tanpa menganggap semua aset sama.
    {"name": "WERKUDARA", "file": "werkudara_new.png", "desc": "Kuat, berani, dan tegas", "source_facing": -1},
    {"name": "ARJUNA", "file": "arjuna_new.png", "desc": "Bijaksana, sabar, dan adil", "source_facing": -1},
    {"name": "BIMA", "file": "bima_new.png", "desc": "Pemberani, pantang menyerah", "source_facing": -1},
    {"name": "SEMAR", "file": "semar.png", "desc": "Bijaksana, sabar, rendah hati, dan setia", "source_facing": -1},
    {"name": "KAPI ANGENI", "file": "kapi_angeni.png", "desc": "Berani, tangguh, bersemangat, dan pantang mundur", "source_facing": 1},
]


def draw_gold_panel(screen, rect, title=None, subtitle=None, selected=False):
    x, y, w, h = rect
    shadow = pygame.Surface((w + 10, h + 10), pygame.SRCALPHA)
    shadow.fill((0, 0, 0, 115))
    screen.blit(shadow, (x + 5, y + 7))
    panel = pygame.Surface((w, h), pygame.SRCALPHA)
    panel.fill((35, 24, 16, 235))
    screen.blit(panel, (x, y))
    pygame.draw.rect(screen, (238, 181, 70) if selected else (154, 105, 39), pygame.Rect(x, y, w, h), 3, border_radius=10)
    pygame.draw.rect(screen, (75, 50, 26), pygame.Rect(x + 8, y + 8, w - 16, h - 16), 1, border_radius=8)
    if title:
        f = pygame.font.SysFont("Georgia", 27, bold=True)
        ts = f.render(title, True, (255, 232, 176))
        screen.blit(ts, (x + 28, y + 22))
    if subtitle:
        sf = pygame.font.SysFont("Arial", 16)
        ss = sf.render(subtitle, True, (225, 215, 195))
        screen.blit(ss, (x + 28, y + 61))


def menu_button_layout(W, H):
    """Return the exact menu button rectangles used for drawing AND mouse input."""
    card_top = int(H * 0.19)
    bottom_reserved = int(H * 0.37)
    card_h = max(190, int(H * 0.43))
    card_h = min(card_h, H - card_top - bottom_reserved)
    card_gap = max(7, int(W * 0.008))
    side_margin = max(24, int(W * 0.055))
    card_w = int((W - side_margin * 2 - card_gap * 4) / 5)
    card_w = max(110, card_w)
    btn_gap_x = max(12, int(W * 0.012))
    btn_gap_y = max(10, int(H * 0.020))
    row_width = min(W - 70, int(W * 0.78))
    btn_w = int((row_width - btn_gap_x * 2) / 3)
    btn_h = max(58, min(78, int(H * 0.095)))
    row1_y = card_top + card_h + max(18, int(H * 0.025))
    row2_y = row1_y + btn_h + btn_gap_y
    row1 = ["story", "attack", "characters"]
    row2 = ["physical", "quiz", "settings"]
    x0 = (W - (btn_w * 3 + btn_gap_x * 2)) // 2
    rects = []
    for i, key in enumerate(row1):
        rects.append((key, pygame.Rect(x0 + i * (btn_w + btn_gap_x), row1_y, btn_w, btn_h)))
    row2_total = btn_w * 3 + btn_gap_x * 2
    x2 = (W - row2_total) // 2
    for i, key in enumerate(row2):
        rects.append((key, pygame.Rect(x2 + i * (btn_w + btn_gap_x), row2_y, btn_w, btn_h)))
    return rects


def quiz_option_layout(W, H, count):
    """Centralized quiz answer cards; kept clear of both side characters."""
    qx = max(250, int(W * 0.235))
    qw = min(int(W * 0.53), W - qx * 2)
    top = int(H * 0.595)
    gap = max(9, int(H * 0.014))
    h = max(45, min(56, int(H * 0.072)))
    return [pygame.Rect(qx, top + i * (h + gap), qw, h) for i in range(count)]


def quiz_popup_layout(W, H):
    panel_w = min(700, W - 110)
    panel_h = min(390, H - 110)
    panel = pygame.Rect((W - panel_w) // 2, (H - panel_h) // 2, panel_w, panel_h)
    button_w = min(500, panel.w - 90)
    button = pygame.Rect(panel.centerx - button_w // 2, panel.bottom - 68, button_w, 48)
    return panel, button

def draw_menu(screen, backgrounds, W, H, big_font, sub_font, text_font, small_font, hover=None):
    """Main menu: centered title, character showcase, clean interactive mode buttons.

    FIX38 UI changes:
    - Removed the stray "PILIH MODE" header.
    - Removed all small descriptions under the mode buttons.
    - Removed emoji icons (font compatibility issues on Windows).
    - Rebalanced the layout so the title never collides with the character cards.
    - Character cards sit above the mode buttons, matching the requested reference.
    """
    draw_background(screen, backgrounds, "ui_batik", W, H)

    # Decorative theatre frame.
    frame = pygame.Rect(10, 10, W - 20, H - 20)
    pygame.draw.rect(screen, (118, 78, 29), frame, 2, border_radius=18)
    pygame.draw.rect(screen, (45, 30, 18), frame.inflate(-18, -18), 1, border_radius=16)

    # ------------------------------------------------------------
    # Title block: intentionally no "PILIH MODE" text here.
    # ------------------------------------------------------------
    title_font = pygame.font.SysFont("Georgia", max(38, min(58, int(H * 0.075))), bold=True)
    tagline_font = pygame.font.SysFont("Georgia", max(20, min(30, int(H * 0.038))), bold=True)
    title = title_font.render("E-DALANG", True, (122, 38, 18))
    tagline = tagline_font.render("EXPERIENCE THE WAYANG DIFFERENTLY", True, (84, 50, 24))
    title_y = max(32, int(H * 0.045))
    screen.blit(title, title.get_rect(center=(W // 2, title_y + title.get_height() // 2)))
    screen.blit(tagline, tagline.get_rect(center=(W // 2, title_y + title.get_height() + 8 + tagline.get_height() // 2)))

    # ------------------------------------------------------------
    # Character showcase.
    # ------------------------------------------------------------
    card_top = int(H * 0.19)
    bottom_reserved = int(H * 0.37)
    card_h = max(190, int(H * 0.43))
    card_h = min(card_h, H - card_top - bottom_reserved)
    card_gap = max(7, int(W * 0.008))
    side_margin = max(24, int(W * 0.055))
    card_w = int((W - side_margin * 2 - card_gap * (len(CHARACTERS) - 1)) / len(CHARACTERS))
    card_w = max(110, card_w)
    total_w = card_w * len(CHARACTERS) + card_gap * (len(CHARACTERS) - 1)
    start_x = (W - total_w) // 2

    mini_title = pygame.font.SysFont("Georgia", max(15, min(22, int(card_w * 0.115))), bold=True)
    mini_desc = pygame.font.SysFont("Arial", max(8, min(12, int(card_w * 0.060))))

    for i, char in enumerate(CHARACTERS):
        x = start_x + i * (card_w + card_gap)
        r = pygame.Rect(x, card_top, card_w, card_h)
        draw_gold_panel(screen, r, None, None, False)

        ts = mini_title.render(char["name"], True, (255, 232, 176))
        screen.blit(ts, ts.get_rect(center=(x + card_w // 2, card_top + 26)))

        try:
            img = pygame.image.load(str(ASSETS / char["file"])).convert_alpha()
            bbox = img.get_bounding_rect(min_alpha=8)
            if bbox.width > 2 and bbox.height > 2:
                img = img.subsurface(bbox).copy()
            max_img_w = card_w - 18
            max_img_h = card_h - 86
            scale = min(max_img_w / img.get_width(), max_img_h / img.get_height())
            img = pygame.transform.smoothscale(
                img,
                (max(1, int(img.get_width() * scale)), max(1, int(img.get_height() * scale)))
            )
            screen.blit(img, img.get_rect(center=(x + card_w // 2, card_top + card_h // 2 + 4)))
        except Exception as exc:
            print(f"[WARNING] Preview karakter {char['name']}: {exc}")

        # Keep the character's trait inside its card.  This is deliberately
        # compact so long traits can never collide with neighboring cards.
        desc_lines = wrap_text(mini_desc, char["desc"], card_w - 18)[:3]
        line_h = mini_desc.get_height() + 1
        dy = card_top + card_h - 10 - line_h * len(desc_lines)
        for line in desc_lines:
            ds = mini_desc.render(line, True, (225, 215, 195))
            screen.blit(ds, ds.get_rect(center=(x + card_w // 2, dy + line_h // 2)))
            dy += line_h

    # ------------------------------------------------------------
    # Mode buttons: title only.  No description text underneath.
    # ------------------------------------------------------------
    buttons = [
        ("MODE STORY", "story"),
        ("GESTURE ATTACK", "attack"),
        ("PILIH KARAKTER", "characters"),
        ("WAYANG FISIK", "physical"),
        ("MODE QUIZ", "quiz"),
        ("PENGATURAN", "settings"),
    ]

    layout = dict(menu_button_layout(W, H))
    btn_h = next(iter(layout.values())).h if layout else 64
    rects = []
    button_font = pygame.font.SysFont("Georgia", max(20, min(30, int(btn_h * 0.39))), bold=True)
    for label, key in buttons:
        r = layout[key]
        rects.append((key, r))
        draw_gold_panel(screen, r, None, None, hover == key)
        ts = button_font.render(label, True, (255, 232, 176))
        # Fit long labels such as GESTURE ATTACK without overflowing.
        if ts.get_width() > r.w - 22:
            fit_font = pygame.font.SysFont("Georgia", max(16, int(button_font.get_height() * 0.80)), bold=True)
            ts = fit_font.render(label, True, (255, 232, 176))
        screen.blit(ts, ts.get_rect(center=r.center))

    # Minimal control hint.  No additional menu descriptions.
    foot_font = pygame.font.SysFont("Arial", max(12, min(17, int(H * 0.022))))
    foot = foot_font.render("1 Story  •  2 Attack  •  3 Karakter  •  4 Fisik  •  5 Quiz  •  6 Pengaturan  •  ESC keluar", True, (84, 50, 24))
    foot_y = H - max(18, int(H * 0.025))
    screen.blit(foot, foot.get_rect(center=(W // 2, foot_y)))
    return rects

# ---------------------------------------------------------------------------
# Layar Pilih Karakter (gaya galeri karakter): grid kartu di kiri, pratinjau
# besar di tengah, info dan pilihan pemain di kanan. Font dan gambar di-cache
# agar tidak dimuat ulang setiap frame.
# ---------------------------------------------------------------------------
_UI_FONTS = {}
_UI_IMGS = {}


def ui_font(name, size, bold=False):
    key = (name, size, bold)
    f = _UI_FONTS.get(key)
    if f is None:
        f = pygame.font.SysFont(name, size, bold=bold)
        _UI_FONTS[key] = f
    return f


def fit_font(name, text, max_w, size, min_size=12, bold=False):
    while size > min_size and ui_font(name, size, bold).size(text)[0] > max_w:
        size -= 1
    return ui_font(name, size, bold)


def char_image(filename, max_w, max_h):
    key = (filename, int(max_w), int(max_h))
    img = _UI_IMGS.get(key)
    if img is None:
        raw = pygame.image.load(str(ASSETS / filename)).convert_alpha()
        bbox = raw.get_bounding_rect(min_alpha=8)
        if bbox.width > 2 and bbox.height > 2:
            raw = raw.subsurface(bbox).copy()
        sc = min(max_w / raw.get_width(), max_h / raw.get_height())
        img = pygame.transform.smoothscale(raw, (max(1, int(raw.get_width() * sc)), max(1, int(raw.get_height() * sc))))
        _UI_IMGS[key] = img
    return img


def soft_glow(w, h, color=(240, 176, 64)):
    key = ("glow", int(w), int(h), color)
    surf = _UI_IMGS.get(key)
    if surf is None:
        surf = pygame.Surface((int(w), int(h)), pygame.SRCALPHA)
        steps = 30
        for i in range(steps):
            f = 1 - i / steps
            ew, eh = max(2, int(w * f)), max(2, int(h * f))
            alpha = int(4 + 62 * (i / steps) ** 2)
            pygame.draw.ellipse(surf, (*color, alpha), pygame.Rect((int(w) - ew) // 2, (int(h) - eh) // 2, ew, eh))
        _UI_IMGS[key] = surf
    return surf


def slot_badge(screen, center, number):
    col = (238, 181, 70) if number == 1 else (196, 64, 42)
    txt = (40, 26, 12) if number == 1 else (255, 240, 220)
    pygame.draw.circle(screen, (20, 12, 8), center, 14)
    pygame.draw.circle(screen, col, center, 12)
    t = ui_font("Georgia", 16, True).render(str(number), True, txt)
    screen.blit(t, t.get_rect(center=center))


def draw_character_menu(screen, backgrounds, W, H, big_font, sub_font, text_font, small_font, left_idx, right_idx, slot, hover=None):
    """Return (cards, back, slot_tabs) berupa rect untuk hit-test klik."""
    mx, my = logical_mouse()
    draw_background(screen, backgrounds, "hutan_sore", W, H)
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((8, 5, 3, 200))
    screen.blit(overlay, (0, 0))

    m = max(28, int(W * 0.035))
    active_idx = left_idx if slot == 0 else right_idx
    now = pygame.time.get_ticks() / 1000.0

    # --- Header -------------------------------------------------------
    title = ui_font("Georgia", max(30, int(H * 0.055)), True).render("PILIH KARAKTER", True, (255, 222, 157))
    screen.blit(title, (m, int(H * 0.03)))
    sub = ui_font("Arial", max(14, int(H * 0.023))).render(
        "Pilih karakter untuk Gesture Attack. Story tetap memakai Bima dan Arjuna.", True, (215, 203, 180))
    screen.blit(sub, (m, int(H * 0.03) + title.get_height() + 2))

    back = pygame.Rect(W - m - 52, int(H * 0.03), 52, 52)
    back_hot = back.collidepoint(mx, my) or hover == "back"
    pygame.draw.circle(screen, (46, 32, 20) if back_hot else (35, 24, 16), back.center, 26)
    pygame.draw.circle(screen, (238, 181, 70) if back_hot else (154, 105, 39), back.center, 26, 3)
    cx0, cy0 = back.center
    pygame.draw.polygon(screen, (255, 226, 158), [(cx0 - 12, cy0), (cx0 - 1, cy0 - 10), (cx0 - 1, cy0 - 4),
                                                  (cx0 + 11, cy0 - 4), (cx0 + 11, cy0 + 4), (cx0 - 1, cy0 + 4),
                                                  (cx0 - 1, cy0 + 10)])

    # --- Grid kartu karakter (kiri) -----------------------------------
    cols = 2
    gap = max(10, int(W * 0.009))
    cw = int(W * 0.108)
    ch = int(cw * 1.26)
    gx, gy = m, int(H * 0.18)
    cards = []
    for i, char in enumerate(CHARACTERS):
        r = pygame.Rect(gx + (i % cols) * (cw + gap), gy + (i // cols) * (ch + gap), cw, ch)
        cards.append((i, r))
        hot = r.collidepoint(mx, my)
        is_active = i == active_idx
        assigned = i in (left_idx, right_idx)

        sh = pygame.Surface((cw + 8, ch + 8), pygame.SRCALPHA)
        sh.fill((0, 0, 0, 100))
        screen.blit(sh, (r.x + 4, r.y + 6))
        body = pygame.Surface((cw, ch), pygame.SRCALPHA)
        body.fill((54, 39, 27, 240) if (hot or is_active) else (36, 26, 18, 235))
        screen.blit(body, r.topleft)
        if is_active:
            border, bw = (255, 244, 214), 3
        elif assigned:
            border, bw = (238, 181, 70), 2
        else:
            border, bw = (122, 86, 40), 2
        pygame.draw.rect(screen, border, r, bw, border_radius=10)

        box_h = ch - 52
        try:
            img = char_image(char["file"], cw - 16, box_h)
            screen.blit(img, img.get_rect(center=(r.centerx, r.y + 8 + box_h // 2)))
        except Exception as exc:
            print(f"[WARNING] Preview karakter {char['name']}: {exc}")

        strip = pygame.Rect(r.x + 6, r.bottom - 38, cw - 12, 30)
        pygame.draw.rect(screen, (238, 220, 184), strip, border_radius=6)
        nf = fit_font("Arial", char["name"], strip.w - 10, 15, 10, True)
        nt = nf.render(char["name"], True, (62, 38, 20))
        screen.blit(nt, nt.get_rect(center=strip.center))

        bx = r.x + 20
        if left_idx == i:
            slot_badge(screen, (bx, r.y + 20), 1)
            bx += 28
        if right_idx == i:
            slot_badge(screen, (bx, r.y + 20), 2)

    # --- Pratinjau besar (tengah) -------------------------------------
    area_l = gx + cols * cw + (cols - 1) * gap + 30
    right_x = W - m - int(W * 0.30)
    cx = (area_l + right_x) // 2
    cy = int(H * 0.52)
    glow = soft_glow(int((right_x - area_l) * 1.05), int(H * 0.88))
    screen.blit(glow, glow.get_rect(center=(cx, cy)))
    active_char = CHARACTERS[active_idx]
    try:
        prev = char_image(active_char["file"], right_x - area_l - 20, int(H * 0.70))
        foot_y = int(cy + H * 0.35)
        bob = math.sin(now * 1.6) * 4
        fs = pygame.Surface((max(40, int(prev.get_width() * 0.8)), 26), pygame.SRCALPHA)
        pygame.draw.ellipse(fs, (0, 0, 0, 120), fs.get_rect())
        screen.blit(fs, fs.get_rect(center=(cx, foot_y + 2)))
        screen.blit(prev, prev.get_rect(midbottom=(cx, int(foot_y + bob))))
    except Exception as exc:
        print(f"[WARNING] Pratinjau karakter: {exc}")

    # --- Info karakter (kanan) ----------------------------------------
    px, pw = right_x, W - m - right_x
    py = int(H * 0.19)
    nf = fit_font("Georgia", active_char["name"], pw, max(30, int(H * 0.06)), 20, True)
    name = nf.render(active_char["name"], True, (255, 222, 157))
    screen.blit(name, (px, py))
    ly = py + name.get_height() + 8
    pygame.draw.line(screen, (190, 138, 52), (px, ly), (px + pw, ly), 2)
    dx = px + pw // 2
    pygame.draw.polygon(screen, (238, 181, 70), [(dx, ly - 6), (dx + 6, ly), (dx, ly + 6), (dx - 6, ly)])
    lab = ui_font("Arial", 14, True).render("SIFAT", True, (190, 138, 52))
    screen.blit(lab, (px, ly + 16))
    body_font = ui_font("Arial", max(17, int(H * 0.028)))
    yy = ly + 16 + lab.get_height() + 6
    for line in wrap_text(body_font, active_char["desc"], pw):
        ls = body_font.render(line, True, (235, 225, 205))
        screen.blit(ls, (px, yy))
        yy += body_font.get_height() + 4

    # --- Pilihan pemain (kanan bawah) ---------------------------------
    tab_h, tab_gap = 58, 10
    ty1 = H - 56 - tab_h
    ty0 = ty1 - tab_gap - tab_h
    cap = ui_font("Arial", 14, True).render("KARAKTER UNTUK", True, (190, 138, 52))
    screen.blit(cap, (px, ty0 - cap.get_height() - 8))
    slot_tabs = []
    for si, idx in enumerate((left_idx, right_idx)):
        r = pygame.Rect(px, ty0 + si * (tab_h + tab_gap), pw, tab_h)
        slot_tabs.append((si, r))
        draw_gold_panel(screen, r, None, None, slot == si)
        if slot != si and r.collidepoint(mx, my):
            pygame.draw.rect(screen, (200, 150, 70), r, 2, border_radius=10)
        slot_badge(screen, (r.x + 32, r.centery), si + 1)
        lbl = ui_font("Georgia", 20, True).render(f"PEMAIN {si + 1}", True, (255, 232, 176))
        screen.blit(lbl, lbl.get_rect(midleft=(r.x + 58, r.centery)))
        nm = ui_font("Arial", 17, True).render(CHARACTERS[idx]["name"], True, (255, 244, 214) if slot == si else (215, 200, 170))
        screen.blit(nm, nm.get_rect(midright=(r.right - 18, r.centery)))

    hint = ui_font("Arial", 15).render(
        "Tekan 1 / 2 untuk memilih pemain  •  Klik kartu untuk memilih karakter  •  ESC kembali", True, (200, 188, 165))
    screen.blit(hint, hint.get_rect(center=(W // 2, H - 22)))
    return cards, back, slot_tabs


# ---------------------------------------------------------------------------
# WAYANG FISIK – Physical puppet controller (Arduino Nano servos + Woodpecker GRBL steppers)
# ---------------------------------------------------------------------------

class PhysicalWayangController:
    """Manages serial connections and high-performance non-blocking asynchronous commands."""

    def __init__(self):
        # Serial connections (defaults prioritized from user's hardware)
        self.nano = None          # Arduino Nano / UNO – servo control
        self.grbl = None          # Woodpecker – GRBL stepper
        self.nano_port = "COM7"
        self.grbl_port = "COM5"
        self.nano_baud = 115200
        self.grbl_baud = 115200

        # Stepper settings
        self.x_min = 0.0
        self.x_max = 200.0
        self.y_min = 0.0
        self.y_max = 200.0
        self.feedrate = 300       # Stepper motor speed in mm/min
        self.servo_angle = 25
        self.interval_kirim = 0.05
        self.deadband = 1.0       # Minimum movement in mm to trigger motor command
        self.langkah_min_mm = 3.0

        # Control modes: "smart" (auto 1 or 2 hands), "2_hands", "1_hand_xy"
        self.stepper_mode = "smart"

        # State
        self.nano_connected = False
        self.grbl_connected = False
        self.running = False
        self.target_x = 0.0
        self.target_y = 0.0
        self.status_servo = {"left": None, "right": None}
        self.status_text = "Belum terhubung"
        self.last_cmd_sent = "Siap"
        self.last_send_time = 0.0

        # Non-blocking async worker queues and threads
        self.grbl_queue = queue.Queue(maxsize=4)
        self.nano_queue = queue.Queue(maxsize=10)
        self.worker_running = True

        self.grbl_thread = threading.Thread(target=self._grbl_worker, daemon=True)
        self.grbl_thread.start()

        self.nano_thread = threading.Thread(target=self._nano_worker, daemon=True)
        self.nano_thread.start()

        # Port scanning cache
        self.available_ports = ["COM5", "COM7", "COM9", "COM4", "COM3", "COM1"]
        self.last_port_scan = 0.0
        self.scan_ports()

    def _grbl_worker(self):
        """Dedicated background worker for Woodpecker GRBL. Eliminates all UI lag."""
        while self.worker_running:
            try:
                cmd = self.grbl_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if not self.grbl_connected or self.grbl is None:
                self.grbl_queue.task_done()
                continue

            try:
                # Coalesce movement updates: skip older intermediate positions if newer ones arrived
                while not self.grbl_queue.empty():
                    try:
                        next_cmd = self.grbl_queue.get_nowait()
                        self.grbl_queue.task_done()
                        if next_cmd.startswith("G1") and cmd.startswith("G1"):
                            cmd = next_cmd
                        else:
                            self._raw_send_grbl(cmd)
                            cmd = next_cmd
                    except queue.Empty:
                        break

                self._raw_send_grbl(cmd)
            except Exception as e:
                print(f"[FISIK] GRBL thread error: {e}")
            finally:
                self.grbl_queue.task_done()

    def _raw_send_grbl(self, command):
        """Send command to GRBL and read response without blocking Pygame."""
        if self.grbl is None or not self.grbl.is_open:
            return False
        try:
            self.grbl.write((command.strip() + "\n").encode("ascii"))
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline and self.worker_running:
                if self.grbl.in_waiting > 0:
                    line = self.grbl.readline().decode("ascii", errors="replace").strip()
                    if line == "ok" or line.startswith("error"):
                        return True
                else:
                    time.sleep(0.005)
            return False
        except Exception as e:
            print(f"[FISIK] GRBL send error: {e}")
            return False

    def _nano_worker(self):
        """Dedicated background worker for Arduino Nano servo commands."""
        while self.worker_running:
            try:
                cmd = self.nano_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if not self.nano_connected or self.nano is None:
                self.nano_queue.task_done()
                continue

            try:
                self.nano.write(cmd.encode("ascii"))
                time.sleep(0.005)
            except Exception as e:
                print(f"[FISIK] Nano thread error: {e}")
            finally:
                self.nano_queue.task_done()

    def queue_grbl(self, command):
        """Enqueue a command for Woodpecker (instant return, zero UI lag)."""
        if not self.grbl_connected:
            return
        try:
            self.grbl_queue.put_nowait(command)
        except queue.Full:
            pass

    def queue_nano(self, command):
        """Enqueue a command for Arduino Nano (instant return, zero UI lag)."""
        if not self.nano_connected:
            return
        try:
            self.nano_queue.put_nowait(command)
        except queue.Full:
            pass

    def scan_ports(self):
        """Scan available COM ports without blocking frequently."""
        now = time.monotonic()
        if now - self.last_port_scan < 3.0 and self.available_ports:
            return self.available_ports
        self.last_port_scan = now
        default_list = ["COM5", "COM7", "COM9", "COM4", "COM3", "COM1"]
        if HAS_SERIAL:
            try:
                ports = [p.device for p in serial.tools.list_ports.comports()]
                merged = list(dict.fromkeys(ports + default_list))
                self.available_ports = merged
            except Exception:
                self.available_ports = default_list
        else:
            self.available_ports = default_list
        return self.available_ports

    def cycle_nano_port(self):
        """Cycle to the next available COM port for Nano."""
        ports = self.scan_ports()
        if not ports:
            return
        try:
            curr_idx = ports.index(self.nano_port)
            self.nano_port = ports[(curr_idx + 1) % len(ports)]
        except ValueError:
            self.nano_port = ports[0]

    def cycle_grbl_port(self):
        """Cycle to the next available COM port for GRBL."""
        ports = self.scan_ports()
        if not ports:
            return
        try:
            curr_idx = ports.index(self.grbl_port)
            self.grbl_port = ports[(curr_idx + 1) % len(ports)]
        except ValueError:
            self.grbl_port = ports[0]

    def connect_nano(self, port=None, baud=115200):
        """Connect to Arduino Nano for servo control."""
        if not HAS_SERIAL:
            self.status_text = "pyserial tidak terinstal!"
            return False
        port = port or self.nano_port
        try:
            if self.nano is not None and self.nano.is_open:
                self.nano.close()
            self.nano = serial.Serial(port, baud, timeout=0.1, write_timeout=1)
            time.sleep(1.5)
            self.nano.reset_input_buffer()
            self.nano_port = port
            self.nano_baud = baud
            self.nano_connected = True
            self.status_text = f"Nano terhubung di {port}"
            print(f"[FISIK] Arduino Nano terhubung di {port}")
            return True
        except Exception as e:
            self.status_text = f"Nano gagal: {e}"
            self.nano_connected = False
            print(f"[FISIK] Nano gagal ({port}): {e}")
            return False

    def disconnect_nano(self):
        while not self.nano_queue.empty():
            try:
                self.nano_queue.get_nowait()
                self.nano_queue.task_done()
            except Exception:
                break
        if self.nano is not None and self.nano.is_open:
            try:
                self.nano.close()
            except Exception:
                pass
        self.nano_connected = False
        self.nano = None

    def connect_grbl(self, port=None, baud=115200):
        """Connect to Woodpecker GRBL board for stepper motors."""
        if not HAS_SERIAL:
            self.status_text = "pyserial tidak terinstal!"
            return False
        port = port or self.grbl_port
        try:
            if self.grbl is not None and self.grbl.is_open:
                self.grbl.close()
            self.grbl = serial.Serial(port, baud, timeout=1, write_timeout=2)
            time.sleep(1.5)
            self.grbl.reset_input_buffer()
            self.grbl_port = port
            self.grbl_baud = baud
            self.grbl_connected = True

            # Inisialisasi GRBL: Bangunkan dan buka alarm ($X)
            self.grbl.write(b"\r\n\r\n")
            time.sleep(0.3)
            self.grbl.write(b"$X\n")
            time.sleep(0.1)
            self.grbl.write(b"G21\n")
            time.sleep(0.1)
            self.grbl.write(b"G90\n")
            self.status_text = f"Woodpecker terhubung di {port}"
            print(f"[FISIK] Woodpecker GRBL terhubung di {port} ($X unlock aktif)")
            return True
        except Exception as e:
            self.status_text = f"GRBL gagal: {e}"
            self.grbl_connected = False
            print(f"[FISIK] GRBL gagal ({port}): {e}")
            return False

    def disconnect_grbl(self):
        while not self.grbl_queue.empty():
            try:
                self.grbl_queue.get_nowait()
                self.grbl_queue.task_done()
            except Exception:
                break
        if self.grbl is not None and self.grbl.is_open:
            try:
                self.grbl.close()
            except Exception:
                pass
        self.grbl_connected = False
        self.grbl = None

    def disconnect_all(self):
        """Close all serial connections."""
        self.running = False
        self.disconnect_nano()
        self.disconnect_grbl()
        self.status_servo = {"left": None, "right": None}
        self.status_text = "Terputus"

    def home_grbl(self):
        """Send homing / go to 0,0 command."""
        if self.grbl_connected:
            self.queue_grbl(f"G1 X0 Y0 F{self.feedrate}")
            self.target_x = 0.0
            self.target_y = 0.0
            self.last_cmd_sent = "G1 X0 Y0 (Home)"
            print("[FISIK] Woodpecker menuju X0 Y0")

    def unlock_grbl(self):
        """Send $X unlock command to GRBL."""
        if self.grbl_connected:
            self.queue_grbl("$X")
            self.last_cmd_sent = "$X (Unlock)"
            print("[FISIK] Perintah $X (unlock) dikirim ke GRBL")

    def jog_step(self, axis, distance):
        """Manually jog stepper by relative distance in mm."""
        if not self.grbl_connected:
            return
        cmd = f"G91\nG1 {axis.upper()}{distance:+.1f} F{self.feedrate}\nG90"
        for c in cmd.split("\n"):
            self.queue_grbl(c)
        if axis.upper() == "X":
            self.target_x = self._clamp(self.target_x + distance, self.x_min, self.x_max)
        elif axis.upper() == "Y":
            self.target_y = self._clamp(self.target_y + distance, self.y_min, self.y_max)
        self.last_cmd_sent = f"JOG {axis.upper()}{distance:+.1f}"

    def test_servo(self):
        """Test servo in a background thread."""
        if not self.nano_connected:
            return
        def _run():
            try:
                self.queue_nano("P")
                time.sleep(0.6)
                self.queue_nano("F")
                time.sleep(0.6)
                self.queue_nano("P")
                print("[FISIK] Tes servo selesai")
            except Exception as e:
                print(f"[FISIK] Error tes servo: {e}")
        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def set_speed(self, speed):
        """Set stepper motor speed (feedrate) in mm/min."""
        self.feedrate = max(50, min(1500, int(speed)))

    def _clamp(self, val, lo, hi):
        return max(lo, min(hi, val))

    def _pos_to_mm(self, normalized, minimum, maximum):
        return minimum + normalized * (maximum - minimum)

    def process_hands(self, hands_dict, W, H):
        """Process detected hands and send non-blocking commands to physical stepper and servos."""
        if not self.running:
            return

        now = time.monotonic()
        if now - self.last_send_time < self.interval_kirim:
            return

        left_hand = hands_dict.get("Left")
        right_hand = hands_dict.get("Right")
        unknown = hands_dict.get("Unknown")

        # -------------------------------------------------------------
        # 1. KONDISI DUA TANGAN (Wayang 1 = X, Wayang 2 = Y)
        # -------------------------------------------------------------
        if left_hand and right_hand:
            # Tangan Kiri -> Sumbu X Stepper
            norm_x = max(0.0, min(1.0, left_hand["palm"].x / W))
            target_x = self._clamp(self._pos_to_mm(norm_x, self.x_min, self.x_max), self.x_min, self.x_max)

            # Tangan Kanan -> Sumbu Y Stepper
            norm_y = max(0.0, min(1.0, right_hand["palm"].x / W))
            target_y = self._clamp(self._pos_to_mm(norm_y, self.y_min, self.y_max), self.y_min, self.y_max)

            parts = []
            if abs(target_x - self.target_x) >= self.deadband:
                self.target_x = target_x
                parts.append(f"X{self.target_x:.1f}")

            if abs(target_y - self.target_y) >= self.deadband:
                self.target_y = target_y
                parts.append(f"Y{self.target_y:.1f}")

            if parts and self.grbl_connected:
                cmd = f"G1 {' '.join(parts)} F{self.feedrate}"
                self.queue_grbl(cmd)
                self.last_cmd_sent = cmd

            # Servo Nano (Gestur kedua tangan)
            if self.nano_connected:
                gl = left_hand.get("gesture", 0)
                cmd_l = "P" if gl == 1 else ("F" if gl == -1 else None)
                if cmd_l and self.status_servo["left"] != cmd_l:
                    self.queue_nano(cmd_l)
                    self.status_servo["left"] = cmd_l

                gr = right_hand.get("gesture", 0)
                cmd_r = "H" if gr == 1 else ("G" if gr == -1 else None)
                if cmd_r and self.status_servo["right"] != cmd_r:
                    self.queue_nano(cmd_r)
                    self.status_servo["right"] = cmd_r

        # -------------------------------------------------------------
        # 2. KONDISI SATU TANGAN (Smart: X Kiri-Kanan, Y Atas-Bawah)
        # -------------------------------------------------------------
        elif left_hand or right_hand or unknown:
            hand = left_hand or right_hand or unknown
            if self.stepper_mode == "2_hands":
                # Mode 2 tangan terpisah (eksklusif)
                if left_hand:
                    norm_x = max(0.0, min(1.0, left_hand["palm"].x / W))
                    target_x = self._clamp(self._pos_to_mm(norm_x, self.x_min, self.x_max), self.x_min, self.x_max)
                    if abs(target_x - self.target_x) >= self.deadband:
                        self.target_x = target_x
                        if self.grbl_connected:
                            cmd = f"G1 X{self.target_x:.1f} F{self.feedrate}"
                            self.queue_grbl(cmd)
                            self.last_cmd_sent = cmd
                elif right_hand:
                    norm_y = max(0.0, min(1.0, right_hand["palm"].x / W))
                    target_y = self._clamp(self._pos_to_mm(norm_y, self.y_min, self.y_max), self.y_min, self.y_max)
                    if abs(target_y - self.target_y) >= self.deadband:
                        self.target_y = target_y
                        if self.grbl_connected:
                            cmd = f"G1 Y{self.target_y:.1f} F{self.feedrate}"
                            self.queue_grbl(cmd)
                            self.last_cmd_sent = cmd
            else:
                # Mode Smart: 1 tangan mengontrol Sumbu X (kiri-kanan) & Sumbu Y (naik-turun)
                norm_x = max(0.0, min(1.0, hand["palm"].x / W))
                target_x = self._clamp(self._pos_to_mm(norm_x, self.x_min, self.x_max), self.x_min, self.x_max)

                # Gerak Atas-Bawah mengontrol Sumbu Y (Tangan naik = Y bertambah)
                norm_y = max(0.0, min(1.0, (H - hand["palm"].y) / H))
                target_y = self._clamp(self._pos_to_mm(norm_y, self.y_min, self.y_max), self.y_min, self.y_max)

                parts = []
                if abs(target_x - self.target_x) >= self.deadband:
                    self.target_x = target_x
                    parts.append(f"X{self.target_x:.1f}")

                if abs(target_y - self.target_y) >= self.deadband:
                    self.target_y = target_y
                    parts.append(f"Y{self.target_y:.1f}")

                if parts and self.grbl_connected:
                    cmd = f"G1 {' '.join(parts)} F{self.feedrate}"
                    self.queue_grbl(cmd)
                    self.last_cmd_sent = cmd

            if self.nano_connected:
                g = hand.get("gesture", 0)
                sisi = "left" if (left_hand or not right_hand) else "right"
                if sisi == "left":
                    cmd_s = "P" if g == 1 else ("F" if g == -1 else None)
                else:
                    cmd_s = "H" if g == 1 else ("G" if g == -1 else None)
                if cmd_s and self.status_servo[sisi] != cmd_s:
                    self.queue_nano(cmd_s)
                    self.status_servo[sisi] = cmd_s

        self.last_send_time = now


# Global physical wayang controller instance
_phys_ctrl = None


def get_phys_controller():
    global _phys_ctrl
    if _phys_ctrl is None:
        _phys_ctrl = PhysicalWayangController()
    return _phys_ctrl


# Cache surface for the theater stage background (drawn once, zero allocation per frame)
_STAGE_CACHE = {}


def get_cached_stage(w, h):
    """Render and cache a dark theater stage background with elegant red curtains."""
    key = (w, h)
    surf = _STAGE_CACHE.get(key)
    if surf is None:
        surf = pygame.Surface((w, h))
        surf.fill((20, 15, 12))

        # Soft dark gradient (no white blowout)
        cx, cy = w // 2, h // 2
        max_r = min(w, h) // 2
        for r in range(max_r, 0, -25):
            alpha = int(22 * (1.0 - r / max_r))
            spot = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.ellipse(spot, (80, 52, 28, alpha), (0, 0, r * 2, r * 2))
            surf.blit(spot, (cx - r, cy - r))

        # Draw left curtain
        curtain_w = max(40, int(w * 0.12))
        for i in range(curtain_w):
            f = i / curtain_w
            shade = int(60 + 35 * math.sin(f * math.pi * 3))
            shade = max(25, min(95, shade))
            alpha = int(220 * (1.0 - f * 0.8))
            col = (shade, int(shade * 0.14), int(shade * 0.16))
            line_s = pygame.Surface((1, h), pygame.SRCALPHA)
            line_s.fill((*col, alpha))
            surf.blit(line_s, (i, 0))

        # Draw right curtain
        for i in range(curtain_w):
            f = i / curtain_w
            shade = int(60 + 35 * math.sin(f * math.pi * 3))
            shade = max(25, min(95, shade))
            alpha = int(220 * (f * 0.8 + 0.2))
            col = (shade, int(shade * 0.14), int(shade * 0.16))
            line_s = pygame.Surface((1, h), pygame.SRCALPHA)
            line_s.fill((*col, alpha))
            surf.blit(line_s, (w - curtain_w + i, 0))

        _STAGE_CACHE[key] = surf
    return surf


def draw_curtains_overlay(surface, w, h):
    """Draw left and right theater curtains over the camera feed."""
    curtain_w = max(40, int(w * 0.10))
    for i in range(curtain_w):
        f = i / curtain_w
        shade = int(55 + 30 * math.sin(f * math.pi * 3))
        shade = max(22, min(90, shade))
        alpha = int(200 * (1.0 - f * 0.85))
        col = (shade, int(shade * 0.14), int(shade * 0.16))
        line_s = pygame.Surface((1, h), pygame.SRCALPHA)
        line_s.fill((*col, alpha))
        surface.blit(line_s, (i, 0))

        alpha_r = int(200 * (f * 0.85 + 0.15))
        line_r = pygame.Surface((1, h), pygame.SRCALPHA)
        line_r.fill((*col, alpha_r))
        surface.blit(line_r, (w - curtain_w + i, 0))


def draw_physical_wayang_ui(screen, backgrounds, W, H, big_font, text_font, small_font,
                             camera_surface=None, ctrl=None, detector_ready=True, fullscreen_pov=False):
    """Draw the Wayang Fisik mode UI with support for fullscreen camera POV and stepper hand drive."""
    if ctrl is None:
        ctrl = get_phys_controller()

    mx, my = logical_mouse()
    rects = {}

    # =========================================================================
    # MODE A: FULLSCREEN POV KAMERA (100% Layar Penuh)
    # =========================================================================
    if fullscreen_pov:
        screen.fill((12, 10, 8))

        # 1. Background Camera Feed (Full window 1280x720)
        if camera_surface is not None:
            cw, ch = camera_surface.get_size()
            if cw != W or ch != H:
                cam_scaled = pygame.transform.scale(camera_surface, (W, H))
            else:
                cam_scaled = camera_surface
            screen.blit(cam_scaled, (0, 0))
        else:
            screen.blit(get_cached_stage(W, H), (0, 0))

        # Curtains overlay on edges
        draw_curtains_overlay(screen, W, H)

        # 2. Top HUD Bar (Translucent)
        top_hud = pygame.Surface((W, 58), pygame.SRCALPHA)
        top_hud.fill((16, 12, 10, 210))
        screen.blit(top_hud, (0, 0))
        pygame.draw.line(screen, (70, 50, 35), (0, 57), (W, 57), 1)

        # Chips: Stepper X & Stepper Y positions
        chip_font = ui_font("Arial", 14, True)
        label_font = ui_font("Arial", 11)

        # Left Chip: Stepper X
        c_x_rect = pygame.Rect(20, 8, 220, 42)
        pygame.draw.rect(screen, (32, 22, 16), c_x_rect, border_radius=8)
        pygame.draw.rect(screen, (220, 160, 45), c_x_rect, 1, border_radius=8)
        screen.blit(label_font.render("STEPPER X (TANGAN KIRI)", True, (190, 165, 130)), (32, 12))
        screen.blit(chip_font.render(f"X: {ctrl.target_x:.1f} mm", True, (255, 225, 140)), (32, 28))

        # Right Chip: Stepper Y
        c_y_rect = pygame.Rect(W - 240, 8, 220, 42)
        pygame.draw.rect(screen, (32, 22, 16), c_y_rect, border_radius=8)
        pygame.draw.rect(screen, (220, 160, 45), c_y_rect, 1, border_radius=8)
        screen.blit(label_font.render("STEPPER Y (TANGAN KANAN)", True, (190, 165, 130)), (W - 228, 12))
        screen.blit(chip_font.render(f"Y: {ctrl.target_y:.1f} mm", True, (255, 225, 140)), (W - 228, 28))

        # Center Status info
        ctr_txt = ui_font("Georgia", 16, True).render(f"Kecepatan: {ctrl.feedrate} mm/min   •   Mode: Tangan Aktif", True, (245, 215, 145))
        screen.blit(ctr_txt, ctr_txt.get_rect(center=(W // 2, 20)))
        stat_txt = ui_font("Arial", 12).render(f"Status GRBL: {ctrl.last_cmd_sent}", True, (70, 220, 120) if ctrl.grbl_connected else (220, 90, 70))
        screen.blit(stat_txt, stat_txt.get_rect(center=(W // 2, 40)))

        # 3. Bottom HUD Bar (Controls)
        bot_hud = pygame.Surface((W, 58), pygame.SRCALPHA)
        bot_hud.fill((16, 12, 10, 210))
        screen.blit(bot_hud, (0, H - 58))
        pygame.draw.line(screen, (70, 50, 35), (0, H - 58), (W, H - 58), 1)

        # Exit Fullscreen Button
        btn_exit_fs = pygame.Rect(20, H - 48, 180, 38)
        rects["toggle_fullscreen"] = btn_exit_fs
        ex_hov = btn_exit_fs.collidepoint(mx, my)
        pygame.draw.rect(screen, (45, 32, 22) if ex_hov else (28, 20, 15), btn_exit_fs, border_radius=8)
        pygame.draw.rect(screen, (240, 180, 50) if ex_hov else (140, 95, 40), btn_exit_fs, 2, border_radius=8)
        screen.blit(ui_font("Arial", 13, True).render("⛶ Keluar Layar Penuh (F)", True, (255, 230, 160)), (btn_exit_fs.x + 12, btn_exit_fs.y + 10))

        # Start / Stop Button
        btn_start_fs = pygame.Rect(W // 2 - 120, H - 48, 240, 38)
        rects["start"] = btn_start_fs
        st_hov = btn_start_fs.collidepoint(mx, my)
        st_col = (150, 45, 30) if ctrl.running else (220, 160, 45)
        pygame.draw.rect(screen, st_col, btn_start_fs, border_radius=8)
        st_lbl = "■  Hentikan (SPACE)" if ctrl.running else "▶  Mulai Pertunjukan (SPACE)"
        st_t = ui_font("Georgia", 15, True).render(st_lbl, True, (255, 255, 255) if ctrl.running else (40, 25, 10))
        screen.blit(st_t, st_t.get_rect(center=btn_start_fs.center))

        # Quick Homing & Speed buttons on right
        btn_home_fs = pygame.Rect(W - 270, H - 48, 70, 38)
        rects["home_grbl"] = btn_home_fs
        hm_hov = btn_home_fs.collidepoint(mx, my)
        pygame.draw.rect(screen, (45, 32, 22) if hm_hov else (28, 20, 15), btn_home_fs, border_radius=8)
        pygame.draw.rect(screen, (240, 180, 50) if hm_hov else (140, 95, 40), btn_home_fs, 1, border_radius=8)
        screen.blit(ui_font("Arial", 12, True).render("Ke 0,0", True, (240, 215, 170)), (btn_home_fs.x + 15, btn_home_fs.y + 11))

        btn_sp_dec = pygame.Rect(W - 190, H - 48, 50, 38)
        btn_sp_inc = pygame.Rect(W - 130, H - 48, 50, 38)
        rects["speed_dec_50"] = btn_sp_dec
        rects["speed_inc_50"] = btn_sp_inc
        for b, txt in [(btn_sp_dec, "-50"), (btn_sp_inc, "+50")]:
            bh = b.collidepoint(mx, my)
            pygame.draw.rect(screen, (45, 32, 22) if bh else (28, 20, 15), b, border_radius=8)
            pygame.draw.rect(screen, (240, 180, 50) if bh else (140, 95, 40), b, 1, border_radius=8)
            bl = ui_font("Arial", 12, True).render(txt, True, (240, 215, 170))
            screen.blit(bl, bl.get_rect(center=b.center))

        return rects

    # =========================================================================
    # MODE B: STANDAR PANGGUNG & SIDEBAR PENGATURAN
    # =========================================================================
    screen.fill((14, 11, 10))

    sidebar_w = max(310, min(390, int(W * 0.31)))
    stage_w = W - sidebar_w
    stage_rect = pygame.Rect(0, 56, stage_w, H - 56)

    # 1. TOP NAVBAR
    nav_h = 56
    nav_bg = pygame.Surface((W, nav_h), pygame.SRCALPHA)
    nav_bg.fill((18, 14, 12, 250))
    screen.blit(nav_bg, (0, 0))
    pygame.draw.line(screen, (45, 34, 25), (0, nav_h - 1), (W, nav_h - 1), 1)

    # Flame icon
    fx, fy = 22, nav_h // 2
    pts = [(fx, fy - 14), (fx + 10, fy + 4), (fx + 6, fy + 14), (fx - 6, fy + 14), (fx - 10, fy + 4)]
    pygame.draw.polygon(screen, (228, 160, 48), pts)
    pygame.draw.polygon(screen, (168, 60, 20), [(fx, fy - 6), (fx + 5, fy + 7), (fx - 5, fy + 7)])

    title_logo = ui_font("Georgia", 22, True).render("E-DALANG", True, (245, 215, 145))
    screen.blit(title_logo, (fx + 18, fy - 16))
    sub_logo = ui_font("Arial", 11).render("Wayang Gesture Controller • Mode Fisik", True, (160, 140, 120))
    screen.blit(sub_logo, (fx + 18, fy + 5))

    # Top right status pills
    pill_y = fy - 12
    pills = [
        ("UNO", ctrl.nano_connected),
        ("Woodpecker", ctrl.grbl_connected),
        ("Kamera", camera_surface is not None),
    ]
    px = W - 20
    for label, is_active in reversed(pills):
        txt = ui_font("Arial", 12).render(label, True, (210, 195, 175))
        pw = txt.get_width() + 26
        px -= pw + 10
        pill_r = pygame.Rect(px, pill_y, pw, 24)
        pygame.draw.rect(screen, (30, 22, 16), pill_r, border_radius=12)
        pygame.draw.rect(screen, (60, 45, 30), pill_r, 1, border_radius=12)
        dot_col = (70, 210, 110) if is_active else (120, 80, 70)
        pygame.draw.circle(screen, dot_col, (pill_r.x + 12, pill_r.centery), 4)
        screen.blit(txt, (pill_r.x + 20, pill_r.centery - txt.get_height() // 2))

    # 2. PANGGUNG WAYANG (LEFT STAGE) - Full stage camera view!
    if camera_surface is not None:
        cw, ch = camera_surface.get_size()
        if cw != stage_rect.w or ch != stage_rect.h:
            cam_view = pygame.transform.scale(camera_surface, (stage_rect.w, stage_rect.h))
        else:
            cam_view = camera_surface
        screen.blit(cam_view, stage_rect.topleft)

        # If not running yet, apply gentle theater dimming
        if not ctrl.running:
            dim = pygame.Surface((stage_rect.w, stage_rect.h), pygame.SRCALPHA)
            dim.fill((10, 7, 5, 140))
            screen.blit(dim, stage_rect.topleft)
    else:
        screen.blit(get_cached_stage(stage_rect.w, stage_rect.h), stage_rect.topleft)

    # Red curtains frame
    draw_curtains_overlay(screen, stage_rect.w, stage_rect.h)

    # Floating top overlay chips
    chip_w = min(220, int(stage_rect.w * 0.28))
    chip_h = 56
    chip_left = pygame.Rect(stage_rect.x + 30, stage_rect.y + 20, chip_w, chip_h)
    chip_right = pygame.Rect(stage_rect.right - chip_w - 30, stage_rect.y + 20, chip_w, chip_h)

    for r, side_name, val_text in [
        (chip_left, "TANGAN KIRI → WAYANG KIRI", f"X {ctrl.target_x:.1f} mm"),
        (chip_right, "TANGAN KANAN → WAYANG KANAN", f"Y {ctrl.target_y:.1f} mm")
    ]:
        cbg = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        cbg.fill((25, 18, 14, 210))
        screen.blit(cbg, r.topleft)
        pygame.draw.rect(screen, (160, 115, 45), r, 1, border_radius=8)
        st = ui_font("Arial", 10, True).render(side_name, True, (190, 165, 130))
        screen.blit(st, (r.x + 12, r.y + 8))
        vt = ui_font("Arial", 16, True).render(val_text, True, (255, 225, 140))
        screen.blit(vt, (r.x + 12, r.y + 28))

    # Center card (when NOT running)
    if not ctrl.running:
        panggung_title = ui_font("Georgia", 36, True).render("PANGGUNG SIAP", True, (255, 230, 160))
        screen.blit(panggung_title, panggung_title.get_rect(center=(stage_rect.centerx, stage_rect.centery - 60)))

        desc_lines = [
            "Hubungkan port COM di panel kanan, lalu mulai",
            "kamera. Tangan kiri menggerakkan wayang kiri, tangan",
            "kanan menggerakkan wayang kanan."
        ]
        dy = stage_rect.centery - 18
        for line in desc_lines:
            ls = ui_font("Arial", 15).render(line, True, (220, 205, 185))
            screen.blit(ls, ls.get_rect(center=(stage_rect.centerx, dy)))
            dy += 22

        # "Mulai Pertunjukan" Button
        btn_start_w = 230
        btn_start_h = 48
        btn_start = pygame.Rect(stage_rect.centerx - btn_start_w // 2, dy + 18, btn_start_w, btn_start_h)
        rects["start"] = btn_start
        st_hov = btn_start.collidepoint(mx, my)
        pygame.draw.rect(screen, (240, 185, 60) if st_hov else (220, 160, 45), btn_start, border_radius=10)
        pygame.draw.rect(screen, (255, 235, 160), btn_start, 2, border_radius=10)
        st_lbl = ui_font("Georgia", 18, True).render("▶  Mulai Pertunjukan", True, (48, 30, 10))
        screen.blit(st_lbl, st_lbl.get_rect(center=btn_start.center))

        status_sub = "Model hand_landmarker siap digunakan." if detector_ready else "Model hand_landmarker belum dimuat."
        sub_s = ui_font("Arial", 12).render(status_sub, True, (180, 160, 135))
        screen.blit(sub_s, sub_s.get_rect(center=(stage_rect.centerx, btn_start.bottom + 22)))
    else:
        # Running: Show stop button and target crosshair indicator on stage
        btn_stop = pygame.Rect(stage_rect.centerx - 110, stage_rect.bottom - 80, 220, 42)
        rects["start"] = btn_stop
        st_hov = btn_stop.collidepoint(mx, my)
        pygame.draw.rect(screen, (160, 45, 30) if st_hov else (125, 32, 22), btn_stop, border_radius=8)
        pygame.draw.rect(screen, (240, 95, 75), btn_stop, 2, border_radius=8)
        bl = ui_font("Georgia", 16, True).render("■  Hentikan Pertunjukan", True, (255, 240, 220))
        screen.blit(bl, bl.get_rect(center=btn_stop.center))

    # Stage Bottom Control Bar
    stage_bot_y = H - 36
    pygame.draw.line(screen, (40, 28, 20), (0, stage_bot_y), (stage_w, stage_bot_y), 1)

    # Back to Menu button
    btn_back = pygame.Rect(20, stage_bot_y + 4, 120, 28)
    rects["back"] = btn_back
    bk_hov = btn_back.collidepoint(mx, my)
    pygame.draw.rect(screen, (40, 28, 18) if bk_hov else (28, 20, 14), btn_back, border_radius=6)
    pygame.draw.rect(screen, (218, 160, 48) if bk_hov else (100, 70, 38), btn_back, 1, border_radius=6)
    screen.blit(ui_font("Arial", 12, True).render("← Menu Utama", True, (245, 215, 145)), (btn_back.x + 15, btn_back.y + 6))

    # Fullscreen POV toggle button
    btn_toggle_fs = pygame.Rect(155, stage_bot_y + 4, 175, 28)
    rects["toggle_fullscreen"] = btn_toggle_fs
    fs_hov = btn_toggle_fs.collidepoint(mx, my)
    pygame.draw.rect(screen, (40, 28, 18) if fs_hov else (28, 20, 14), btn_toggle_fs, border_radius=6)
    pygame.draw.rect(screen, (240, 185, 60) if fs_hov else (120, 85, 45), btn_toggle_fs, 1, border_radius=6)
    screen.blit(ui_font("Arial", 12, True).render("⛶ Layar Penuh POV (F)", True, (255, 230, 150)), (btn_toggle_fs.x + 12, btn_toggle_fs.y + 6))

    # FPS counter on stage
    screen.blit(ui_font("Arial", 11).render("30 fps", True, (140, 125, 105)), (stage_w - 55, stage_bot_y + 10))

    # 3. RIGHT SIDEBAR: CONTROLS & SETTINGS
    side_rect = pygame.Rect(stage_w, nav_h, sidebar_w, H - nav_h)
    side_bg = pygame.Surface((sidebar_w, side_rect.h), pygame.SRCALPHA)
    side_bg.fill((20, 15, 13, 245))
    screen.blit(side_bg, side_rect.topleft)
    pygame.draw.line(screen, (45, 34, 25), (stage_w, nav_h), (stage_w, H), 2)

    pad = 12
    card_w = sidebar_w - pad * 2
    cur_y = nav_h + 10

    # -------------------------------------------------------------------------
    # CARD 1: Arduino UNO (servo wayang)
    # -------------------------------------------------------------------------
    card1_h = 135
    c1_rect = pygame.Rect(stage_w + pad, cur_y, card_w, card1_h)
    pygame.draw.rect(screen, (28, 20, 17), c1_rect, border_radius=10)
    pygame.draw.rect(screen, (55, 40, 30), c1_rect, 1, border_radius=10)

    uno_hdr = ui_font("Georgia", 16, True).render("Arduino UNO", True, (245, 215, 145))
    uno_sub = ui_font("Arial", 11).render("servo wayang", True, (160, 140, 120))
    screen.blit(uno_hdr, (c1_rect.x + 12, c1_rect.y + 10))
    screen.blit(uno_sub, (c1_rect.x + 12 + uno_hdr.get_width() + 6, c1_rect.y + 14))

    ub_txt = ui_font("Arial", 11, True).render("Terhubung" if ctrl.nano_connected else "Terputus", True, (60, 190, 90) if ctrl.nano_connected else (190, 80, 70))
    screen.blit(ub_txt, (c1_rect.right - ub_txt.get_width() - 12, c1_rect.y + 12))

    # Port row
    port_row_y = c1_rect.y + 36
    screen.blit(ui_font("Arial", 11).render("Port COM", True, (150, 135, 115)), (c1_rect.x + 12, port_row_y))
    screen.blit(ui_font("Arial", 11).render("Baud", True, (150, 135, 115)), (c1_rect.right - 65, port_row_y))

    port_btn_w = card_w - 95
    btn_nano_port = pygame.Rect(c1_rect.x + 12, port_row_y + 16, port_btn_w, 26)
    rects["cycle_nano_port"] = btn_nano_port
    p_hov = btn_nano_port.collidepoint(mx, my)
    pygame.draw.rect(screen, (38, 28, 22) if p_hov else (24, 18, 14), btn_nano_port, border_radius=5)
    pygame.draw.rect(screen, (180, 130, 45) if p_hov else (60, 45, 32), btn_nano_port, 1, border_radius=5)
    p_txt = ui_font("Arial", 12).render(f"▾ {ctrl.nano_port or 'Pilih port...'}", True, (230, 215, 190))
    screen.blit(p_txt, (btn_nano_port.x + 8, btn_nano_port.centery - p_txt.get_height() // 2))

    baud_box = pygame.Rect(c1_rect.right - 72, port_row_y + 16, 60, 26)
    pygame.draw.rect(screen, (24, 18, 14), baud_box, border_radius=5)
    pygame.draw.rect(screen, (60, 45, 32), baud_box, 1, border_radius=5)
    screen.blit(ui_font("Arial", 11).render("115200", True, (190, 175, 155)), (baud_box.x + 10, baud_box.y + 6))

    # Buttons
    btn_y = port_row_y + 48
    btn_conn_nano = pygame.Rect(c1_rect.x + 12, btn_y, int(card_w * 0.58), 30)
    rects["connect_nano"] = btn_conn_nano
    cn_hov = btn_conn_nano.collidepoint(mx, my)
    cn_col = (190, 70, 50) if ctrl.nano_connected else ((228, 170, 50) if cn_hov else (208, 150, 40))
    pygame.draw.rect(screen, cn_col, btn_conn_nano, border_radius=6)
    cn_txt = ui_font("Arial", 12, True).render("Putuskan" if ctrl.nano_connected else "Hubungkan", True, (255, 255, 255) if ctrl.nano_connected else (40, 25, 10))
    screen.blit(cn_txt, cn_txt.get_rect(center=btn_conn_nano.center))

    btn_test_servo = pygame.Rect(btn_conn_nano.right + 8, btn_y, card_w - btn_conn_nano.w - 32, 30)
    rects["test_servo"] = btn_test_servo
    ts_hov = btn_test_servo.collidepoint(mx, my)
    pygame.draw.rect(screen, (45, 32, 24) if ts_hov else (32, 24, 18), btn_test_servo, border_radius=6)
    pygame.draw.rect(screen, (180, 130, 45) if ts_hov else (60, 45, 32), btn_test_servo, 1, border_radius=6)
    ts_txt = ui_font("Arial", 12).render("Tes servo", True, (230, 215, 190))
    screen.blit(ts_txt, ts_txt.get_rect(center=btn_test_servo.center))

    cur_y += card1_h + 10

    # -------------------------------------------------------------------------
    # CARD 2: Woodpecker (GRBL · rel X/Y)
    # -------------------------------------------------------------------------
    card2_h = 168
    c2_rect = pygame.Rect(stage_w + pad, cur_y, card_w, card2_h)
    pygame.draw.rect(screen, (28, 20, 17), c2_rect, border_radius=10)
    pygame.draw.rect(screen, (55, 40, 30), c2_rect, 1, border_radius=10)

    wp_hdr = ui_font("Georgia", 16, True).render("Woodpecker", True, (245, 215, 145))
    wp_sub = ui_font("Arial", 11).render("GRBL • rel X/Y", True, (160, 140, 120))
    screen.blit(wp_hdr, (c2_rect.x + 12, c2_rect.y + 10))
    screen.blit(wp_sub, (c2_rect.x + 12 + wp_hdr.get_width() + 6, c2_rect.y + 14))

    gb_txt = ui_font("Arial", 11, True).render("Terhubung" if ctrl.grbl_connected else "Terputus", True, (60, 190, 90) if ctrl.grbl_connected else (190, 80, 70))
    screen.blit(gb_txt, (c2_rect.right - gb_txt.get_width() - 12, c2_rect.y + 12))

    # Port row
    port_row_y2 = c2_rect.y + 36
    screen.blit(ui_font("Arial", 11).render("Port COM", True, (150, 135, 115)), (c2_rect.x + 12, port_row_y2))
    screen.blit(ui_font("Arial", 11).render("Baud", True, (150, 135, 115)), (c2_rect.right - 65, port_row_y2))

    btn_grbl_port = pygame.Rect(c2_rect.x + 12, port_row_y2 + 16, port_btn_w, 26)
    rects["cycle_grbl_port"] = btn_grbl_port
    gp_hov = btn_grbl_port.collidepoint(mx, my)
    pygame.draw.rect(screen, (38, 28, 22) if gp_hov else (24, 18, 14), btn_grbl_port, border_radius=5)
    pygame.draw.rect(screen, (180, 130, 45) if gp_hov else (60, 45, 32), btn_grbl_port, 1, border_radius=5)
    gp_txt = ui_font("Arial", 12).render(f"▾ {ctrl.grbl_port or 'Pilih port...'}", True, (230, 215, 190))
    screen.blit(gp_txt, (btn_grbl_port.x + 8, btn_grbl_port.centery - gp_txt.get_height() // 2))

    baud_box2 = pygame.Rect(c2_rect.right - 72, port_row_y2 + 16, 60, 26)
    pygame.draw.rect(screen, (24, 18, 14), baud_box2, border_radius=5)
    pygame.draw.rect(screen, (60, 45, 32), baud_box2, 1, border_radius=5)
    screen.blit(ui_font("Arial", 11).render("115200", True, (190, 175, 155)), (baud_box2.x + 10, baud_box2.y + 6))

    # Connection buttons
    btn_y2 = port_row_y2 + 48
    btn_conn_grbl = pygame.Rect(c2_rect.x + 12, btn_y2, int(card_w * 0.44), 30)
    rects["connect_grbl"] = btn_conn_grbl
    cg_hov = btn_conn_grbl.collidepoint(mx, my)
    cg_col = (190, 70, 50) if ctrl.grbl_connected else ((228, 170, 50) if cg_hov else (208, 150, 40))
    pygame.draw.rect(screen, cg_col, btn_conn_grbl, border_radius=6)
    cg_txt = ui_font("Arial", 12, True).render("Putuskan" if ctrl.grbl_connected else "Hubungkan", True, (255, 255, 255) if ctrl.grbl_connected else (40, 25, 10))
    screen.blit(cg_txt, cg_txt.get_rect(center=btn_conn_grbl.center))

    btn_home = pygame.Rect(btn_conn_grbl.right + 6, btn_y2, int(card_w * 0.26), 30)
    rects["home_grbl"] = btn_home
    hm_hov = btn_home.collidepoint(mx, my)
    pygame.draw.rect(screen, (45, 32, 24) if hm_hov else (32, 24, 18), btn_home, border_radius=6)
    pygame.draw.rect(screen, (180, 130, 45) if hm_hov else (60, 45, 32), btn_home, 1, border_radius=6)
    screen.blit(ui_font("Arial", 11).render("Ke 0,0", True, (230, 215, 190)), (btn_home.x + 12, btn_home.y + 8))

    btn_unlock = pygame.Rect(btn_home.right + 6, btn_y2, card_w - btn_conn_grbl.w - btn_home.w - 36, 30)
    rects["unlock_grbl"] = btn_unlock
    ul_hov = btn_unlock.collidepoint(mx, my)
    pygame.draw.rect(screen, (45, 32, 24) if ul_hov else (32, 24, 18), btn_unlock, border_radius=6)
    pygame.draw.rect(screen, (180, 130, 45) if ul_hov else (60, 45, 32), btn_unlock, 1, border_radius=6)
    screen.blit(ui_font("Arial", 11, True).render("$X", True, (245, 215, 145)), (btn_unlock.x + 12, btn_unlock.y + 8))

    # Stepper Motor Manual Jog Buttons Row
    jog_y = btn_y2 + 36
    screen.blit(ui_font("Arial", 10, True).render("UJI MANUAL STEPPER MOTOR:", True, (160, 140, 120)), (c2_rect.x + 12, jog_y))
    jog_btns = [
        ("X -10", "jog_x_minus"),
        ("X +10", "jog_x_plus"),
        ("Y -10", "jog_y_minus"),
        ("Y +10", "jog_y_plus"),
    ]
    jw = (card_w - 42) // 4
    for i, (j_lbl, j_key) in enumerate(jog_btns):
        jr = pygame.Rect(c2_rect.x + 12 + i * (jw + 6), jog_y + 16, jw, 24)
        rects[j_key] = jr
        jh = jr.collidepoint(mx, my)
        pygame.draw.rect(screen, (45, 32, 22) if jh else (30, 22, 16), jr, border_radius=5)
        pygame.draw.rect(screen, (220, 160, 45) if jh else (65, 48, 35), jr, 1, border_radius=5)
        jt = ui_font("Arial", 10, True).render(j_lbl, True, (245, 225, 185))
        screen.blit(jt, jt.get_rect(center=jr.center))

    cur_y += card2_h + 10

    # -------------------------------------------------------------------------
    # CARD 3: PENGATURAN (Settings + Stepper Speed Control)
    # -------------------------------------------------------------------------
    card3_h = H - cur_y - 10
    c3_rect = pygame.Rect(stage_w + pad, cur_y, card_w, card3_h)
    pygame.draw.rect(screen, (28, 20, 17), c3_rect, border_radius=10)
    pygame.draw.rect(screen, (55, 40, 30), c3_rect, 1, border_radius=10)

    set_hdr = ui_font("Georgia", 16, True).render("Pengaturan", True, (245, 215, 145))
    screen.blit(set_hdr, (c3_rect.x + 12, c3_rect.y + 10))

    # Grid 2x2 parameter display
    grid_y = c3_rect.y + 32
    col_w = (card_w - 30) // 2
    row_gap = 34

    params = [
        ("X min (mm)", f"{ctrl.x_min:.0f}", "X max (mm)", f"{ctrl.x_max:.0f}"),
        ("Y min (mm)", f"{ctrl.y_min:.0f}", "Y max (mm)", f"{ctrl.y_max:.0f}"),
        ("Feedrate", f"{ctrl.feedrate}", "Sudut servo (°)", f"{ctrl.servo_angle}"),
    ]

    gy = grid_y
    for l1, v1, l2, v2 in params:
        lbl1 = ui_font("Arial", 10).render(l1, True, (150, 135, 115))
        screen.blit(lbl1, (c3_rect.x + 12, gy))
        box1 = pygame.Rect(c3_rect.x + 12, gy + 14, col_w, 22)
        pygame.draw.rect(screen, (22, 16, 12), box1, border_radius=4)
        pygame.draw.rect(screen, (50, 38, 28), box1, 1, border_radius=4)
        vt1 = ui_font("Arial", 11, True).render(v1, True, (230, 215, 190))
        screen.blit(vt1, (box1.x + 6, box1.centery - vt1.get_height() // 2))

        lbl2 = ui_font("Arial", 10).render(l2, True, (150, 135, 115))
        screen.blit(lbl2, (c3_rect.x + 18 + col_w, gy))
        box2 = pygame.Rect(c3_rect.x + 18 + col_w, gy + 14, col_w, 22)
        pygame.draw.rect(screen, (22, 16, 12), box2, border_radius=4)
        pygame.draw.rect(screen, (50, 38, 28), box2, 1, border_radius=4)
        vt2 = ui_font("Arial", 11, True).render(v2, True, (230, 215, 190))
        screen.blit(vt2, (box2.x + 6, box2.centery - vt2.get_height() // 2))

        gy += row_gap + 4

    # STEPPER MOTOR SPEED ADJUSTMENT
    spd_y = gy + 4
    spd_hdr = ui_font("Georgia", 14, True).render("Kecepatan Motor Stepper", True, (245, 215, 145))
    screen.blit(spd_hdr, (c3_rect.x + 12, spd_y))

    spd_val_txt = ui_font("Arial", 14, True).render(f"{ctrl.feedrate} mm/min", True, (255, 225, 130))
    screen.blit(spd_val_txt, (c3_rect.right - spd_val_txt.get_width() - 12, spd_y))

    # Interactive slider bar
    bar_y = spd_y + 24
    bar_w = card_w - 24
    bar_h = 16
    slider_bar = pygame.Rect(c3_rect.x + 12, bar_y, bar_w, bar_h)
    rects["speed_bar"] = slider_bar

    pygame.draw.rect(screen, (22, 16, 12), slider_bar, border_radius=8)
    pygame.draw.rect(screen, (65, 48, 35), slider_bar, 1, border_radius=8)

    pct = max(0.0, min(1.0, (ctrl.feedrate - 50) / 1150.0))
    fill_w = max(4, int(bar_w * pct))
    fill_rect = pygame.Rect(slider_bar.x, slider_bar.y, fill_w, bar_h)
    pygame.draw.rect(screen, (218, 150, 45), fill_rect, border_radius=8)

    handle_cx = slider_bar.x + fill_w
    pygame.draw.circle(screen, (255, 230, 150), (handle_cx, slider_bar.centery), 9)
    pygame.draw.circle(screen, (160, 100, 20), (handle_cx, slider_bar.centery), 9, 2)

    # Quick speed adjustment buttons (-50, -10, +10, +50)
    btns_y = bar_y + bar_h + 8
    btn_specs = [
        ("-50", -50, "speed_dec_50"),
        ("-10", -10, "speed_dec_10"),
        ("+10", +10, "speed_inc_10"),
        ("+50", +50, "speed_inc_50"),
    ]
    b_gap = 6
    b_width = (bar_w - b_gap * 3) // 4
    for i, (b_label, delta, r_key) in enumerate(btn_specs):
        bx = slider_bar.x + i * (b_width + b_gap)
        br = pygame.Rect(bx, btns_y, b_width, 24)
        rects[r_key] = br
        b_hov = br.collidepoint(mx, my)
        pygame.draw.rect(screen, (45, 32, 22) if b_hov else (30, 22, 16), br, border_radius=5)
        pygame.draw.rect(screen, (200, 140, 45) if b_hov else (55, 40, 28), br, 1, border_radius=5)
        bt = ui_font("Arial", 11, True).render(b_label, True, (240, 220, 180))
        screen.blit(bt, bt.get_rect(center=br.center))

    # Stepper Mode Toggle Button (Smart / 2 Tangan)
    mode_y = btns_y + 30
    btn_mode = pygame.Rect(c3_rect.x + 12, mode_y, card_w - 24, 26)
    rects["toggle_stepper_mode"] = btn_mode
    mh = btn_mode.collidepoint(mx, my)
    pygame.draw.rect(screen, (45, 32, 22) if mh else (28, 20, 15), btn_mode, border_radius=5)
    pygame.draw.rect(screen, (220, 160, 45) if mh else (65, 48, 35), btn_mode, 1, border_radius=5)
    mode_lbl = "Mode Stepper: Smart (1 / 2 Tangan)" if ctrl.stepper_mode == "smart" else "Mode Stepper: 2 Tangan (X/Y Terpisah)"
    mt = ui_font("Arial", 11, True).render(mode_lbl, True, (245, 220, 160))
    screen.blit(mt, mt.get_rect(center=btn_mode.center))

    # Reset Defaults Button
    def_y = mode_y + 30
    btn_defaults = pygame.Rect(c3_rect.x + 12, def_y, card_w - 24, 26)
    rects["defaults"] = btn_defaults
    df_hov = btn_defaults.collidepoint(mx, my)
    pygame.draw.rect(screen, (38, 28, 20) if df_hov else (26, 18, 14), btn_defaults, border_radius=5)
    pygame.draw.rect(screen, (180, 130, 45) if df_hov else (55, 40, 28), btn_defaults, 1, border_radius=5)
    df_txt = ui_font("Arial", 11).render("Kembalikan default", True, (200, 180, 150))
    screen.blit(df_txt, df_txt.get_rect(center=btn_defaults.center))

    return rects


def draw_settings(screen, backgrounds, W, H, big_font, text_font, small_font, show_pov, music_on):
    draw_background(screen, backgrounds, "hutan_sore", W, H)
    overlay = pygame.Surface((W,H), pygame.SRCALPHA); overlay.fill((5,4,3,190)); screen.blit(overlay,(0,0))
    title = big_font.render("PENGATURAN", True, (255,222,157)); screen.blit(title, title.get_rect(center=(W//2,85)))
    rows = [
        ("POV TANGAN", "Jendela kamera terpisah", show_pov),
        ("MUSIK", "Musik latar mode story", music_on),
    ]
    rects=[]
    for i,(name,desc,on) in enumerate(rows):
        r=pygame.Rect(W//2-330,180+i*125,660,92); rects.append(r)
        draw_gold_panel(screen,r,name,desc,False)
        status=small_font.render("AKTIF" if on else "NONAKTIF",True,(255,225,160) if on else (190,180,165))
        screen.blit(status,status.get_rect(midright=(r.right-25,r.centery)))
    back=pygame.Rect(45,H-70,180,45); draw_gold_panel(screen,back,"KEMBALI","",False)
    hint=small_font.render("Klik pengaturan untuk mengubah • ESC kembali",True,(225,215,195)); screen.blit(hint,hint.get_rect(center=(W//2,H-35)))
    return rects,back


def _load_character_image(char_name, target_height):
    """Load a menu/quiz character image, crop transparent padding and scale it."""
    char = next((c for c in CHARACTERS if c["name"] == char_name), None)
    if not char:
        return None
    path = ASSETS / char["file"]
    if not path.exists():
        return None
    try:
        img = pygame.image.load(str(path)).convert_alpha()
        bbox = img.get_bounding_rect(min_alpha=8)
        if bbox.width > 2 and bbox.height > 2:
            img = img.subsurface(bbox).copy()
        ratio = target_height / max(1, img.get_height())
        img = pygame.transform.smoothscale(img, (max(1, int(img.get_width()*ratio)), max(1, int(img.get_height()*ratio))))
        return img, char.get("source_facing", 1)
    except Exception as exc:
        print(f"[WARNING] Gagal memuat karakter {char_name}: {exc}")
        return None


def _inward_character(screen, char_name, center, target_height, wanted_facing):
    loaded = _load_character_image(char_name, target_height)
    if not loaded:
        return
    img, source_facing = loaded
    if source_facing != wanted_facing:
        img = pygame.transform.flip(img, True, False)
    rect = img.get_rect(center=(int(center[0]), int(center[1])))
    # Subtle glow silhouette like the reference UI.
    try:
        mask = pygame.mask.from_surface(img, 8)
        halo = mask.to_surface(setcolor=(205, 151, 53, 120), unsetcolor=(0, 0, 0, 0))
        halo.set_colorkey((0, 0, 0, 0))
        screen.blit(halo, (rect.x-2, rect.y-2))
    except Exception:
        pass
    screen.blit(img, rect)


def _draw_quiz_answer_card(screen, rect, number, text, font, selected=False, correct=False, wrong=False, hover=False):
    """Draw one clean answer card; text is vertically centered and never shares a title row."""
    if correct:
        border = (94, 190, 112)
    elif wrong:
        border = (204, 76, 76)
    elif selected or hover:
        border = (238, 181, 70)
    else:
        border = (154, 105, 39)
    shadow = pygame.Surface((rect.w + 8, rect.h + 8), pygame.SRCALPHA)
    shadow.fill((0, 0, 0, 105))
    screen.blit(shadow, (rect.x + 4, rect.y + 5))
    pygame.draw.rect(screen, (35, 24, 16), rect, border_radius=10)
    pygame.draw.rect(screen, border, rect, 2, border_radius=10)
    pygame.draw.rect(screen, (76, 51, 27), rect.inflate(-8, -8), 1, border_radius=8)

    cx = rect.x + 35
    pygame.draw.circle(screen, (25, 18, 11), (cx, rect.centery), 17)
    pygame.draw.circle(screen, border, (cx, rect.centery), 17, 2)
    ns = pygame.font.SysFont("Georgia", 21, bold=True).render(str(number), True, (255, 231, 169))
    screen.blit(ns, ns.get_rect(center=(cx, rect.centery + 1)))

    available = rect.w - 82
    fs = font
    if fs.size(text)[0] > available:
        fs = pygame.font.SysFont("Arial", max(16, min(23, font.get_height() - 2)))
    lines = wrap_text(fs, text, available)
    if len(lines) > 2:
        fs = pygame.font.SysFont("Arial", max(15, fs.get_height() - 2))
        lines = wrap_text(fs, text, available)[:2]
    total_h = len(lines) * fs.get_height()
    yy = rect.centery - total_h // 2
    for line in lines:
        surf = fs.render(line, True, (255, 239, 210))
        screen.blit(surf, surf.get_rect(midleft=(rect.x + 66, yy + fs.get_height() // 2)))
        yy += fs.get_height()


def _draw_quiz_popup(screen, W, H, q, selected, quiz_index, font, small_font):
    """Reference-style correct/wrong popup shown after an answer is selected."""
    correct = selected == q["answer"]
    dim = pygame.Surface((W, H), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 175))
    screen.blit(dim, (0, 0))

    panel, button = quiz_popup_layout(W, H)
    outer = (74, 185, 112) if correct else (211, 73, 73)
    inner = (13, 55, 35) if correct else (66, 25, 23)
    pygame.draw.rect(screen, (18, 12, 8), panel, border_radius=24)
    pygame.draw.rect(screen, outer, panel, 4, border_radius=24)
    pygame.draw.rect(screen, (157, 109, 44), panel.inflate(-12, -12), 2, border_radius=18)

    icon_center = (panel.centerx, panel.y + 68)
    pygame.draw.circle(screen, inner, icon_center, 48)
    pygame.draw.circle(screen, outer, icon_center, 48, 3)
    if correct:
        pygame.draw.line(screen, (255, 232, 170), (icon_center[0]-20, icon_center[1]+2), (icon_center[0]-5, icon_center[1]+17), 7)
        pygame.draw.line(screen, (255, 232, 170), (icon_center[0]-5, icon_center[1]+17), (icon_center[0]+23, icon_center[1]-19), 7)
    else:
        pygame.draw.line(screen, (255, 215, 190), (icon_center[0]-18, icon_center[1]-18), (icon_center[0]+18, icon_center[1]+18), 7)
        pygame.draw.line(screen, (255, 215, 190), (icon_center[0]+18, icon_center[1]-18), (icon_center[0]-18, icon_center[1]+18), 7)

    title = "BENAR!" if correct else "SALAH!"
    subtitle = "Hebat! Jawaban Anda tepat." if correct else "Coba lagi! Jawaban kurang tepat."
    tf = pygame.font.SysFont("Georgia", 42, bold=True)
    sf = pygame.font.SysFont("Arial", 22, bold=True)
    ts = tf.render(title, True, (245, 239, 220))
    ss = sf.render(subtitle, True, (238, 228, 207))
    screen.blit(ts, ts.get_rect(center=(panel.centerx, panel.y + 142)))
    screen.blit(ss, ss.get_rect(center=(panel.centerx, panel.y + 178)))

    explanation = q.get("explanation", "")
    ef = pygame.font.SysFont("Arial", 20)
    lines = wrap_text(ef, explanation, panel.w - 100)[:3]
    yy = panel.y + 210
    for line in lines:
        es = ef.render(line, True, (232, 223, 204))
        screen.blit(es, es.get_rect(center=(panel.centerx, yy)))
        yy += 26

    button_fill = (31, 100, 55) if correct else (112, 35, 35)
    pygame.draw.rect(screen, button_fill, button, border_radius=10)
    pygame.draw.rect(screen, outer, button, 2, border_radius=10)
    label = "LANJUTKAN KE PERTANYAAN BERIKUTNYA" if correct else "ULANGI PERTANYAAN"
    bs = pygame.font.SysFont("Arial", 20, bold=True).render(label, True, (255, 244, 220))
    screen.blit(bs, bs.get_rect(center=button.center))

    step = small_font.render(f"Soal {quiz_index + 1:02d}", True, (226, 207, 169))
    screen.blit(step, step.get_rect(center=(panel.centerx, panel.y + 28)))
    return button


def draw_quiz_ui(screen, backgrounds, W, H, big_font, sub_font, text_font, small_font, quiz_index, quiz_score, selected, finished=False):
    """Clean audience quiz layout based on the supplied reference."""
    draw_background(screen, backgrounds, "ui_edalang", W, H)
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((5, 4, 3, 150))
    screen.blit(overlay, (0, 0))

    frame = pygame.Rect(14, 14, W - 28, H - 28)
    pygame.draw.rect(screen, (160, 109, 39), frame, 2, border_radius=16)
    pygame.draw.rect(screen, (63, 42, 23), frame.inflate(-14, -14), 1, border_radius=12)

    title_font = pygame.font.SysFont("Georgia", max(38, min(52, int(H * 0.070))), bold=True)
    title = title_font.render("KUIS PENONTON", True, (255, 224, 155))
    screen.blit(title, title.get_rect(center=(W // 2, 58)))

    side_h = min(245, max(185, int(H * 0.33)))
    _inward_character(screen, "BIMA", (max(120, int(W * 0.11)), int(H * 0.57)), side_h, 1)
    _inward_character(screen, "ARJUNA", (min(W - 120, int(W * 0.89)), int(H * 0.57)), side_h, -1)

    count = len(QUIZ_QUESTIONS)
    rail_w = min(430, int(W * 0.36))
    rail = pygame.Rect((W - rail_w) // 2, 108, rail_w, 54)
    pygame.draw.rect(screen, (24, 16, 9), rail, border_radius=20)
    pygame.draw.rect(screen, (151, 99, 33), rail, 2, border_radius=20)
    label = small_font.render("PERJALANAN CERITA", True, (238, 203, 141))
    screen.blit(label, label.get_rect(center=(W // 2, 120)))
    x0, x1 = rail.x + 35, rail.right - 35
    yline = 143
    pygame.draw.line(screen, (193, 137, 51), (x0, yline), (x1, yline), 3)
    for i in range(count):
        x = int(x0 + (x1 - x0) * (i / max(1, count - 1)))
        active = i <= quiz_index if not finished else True
        pygame.draw.circle(screen, (255, 210, 101) if active else (31, 23, 15), (x, yline), 9)
        pygame.draw.circle(screen, (132, 89, 31), (x, yline), 9, 2)

    num_box = pygame.Rect(W // 2 - 58, 166, 116, 38)
    draw_gold_panel(screen, num_box, None, None, False)
    num = small_font.render(f"{quiz_index + 1:02d} / {count:02d}" if not finished else f"{count:02d} / {count:02d}", True, (255, 231, 169))
    screen.blit(num, num.get_rect(center=num_box.center))

    if finished:
        result = pygame.Rect(max(170, W // 2 - 330), 245, min(660, W - 340), 285)
        draw_gold_panel(screen, result, "KUIS SELESAI", None, True)
        score = sub_font.render(f"SKOR {quiz_score} / {count}", True, (255, 231, 169))
        screen.blit(score, score.get_rect(center=(W // 2, 330)))
        msg = ("Luar biasa! Kamu memahami kisahnya dengan sangat baik." if quiz_score == count
               else "Bagus! Kamu sudah memahami sebagian besar pesan cerita." if quiz_score >= 3
               else "Tetap semangat! Coba ingat kembali perjalanan Bima dan Arjuna.")
        yy = 385
        for line in wrap_text(text_font, msg, result.w - 80)[:3]:
            ss = text_font.render(line, True, (235, 225, 205))
            screen.blit(ss, ss.get_rect(center=(W // 2, yy)))
            yy += 30
        hint = small_font.render("M / ESC / KEMBALI = menu utama", True, (255, 226, 163))
        screen.blit(hint, hint.get_rect(center=(W // 2, H - 35)))
        return [], pygame.Rect(34, H - 68, 205, 46), None

    q = QUIZ_QUESTIONS[quiz_index]
    qx = max(270, int(W * 0.22))
    qw = min(int(W * 0.56), W - qx * 2)
    qhead = pygame.Rect(qx, 222, qw, 44)
    qbox = pygame.Rect(qx, 266, qw, 118)

    pygame.draw.rect(screen, (35, 24, 16), qbox, border_radius=12)
    pygame.draw.rect(screen, (154, 105, 39), qbox, 2, border_radius=12)
    pygame.draw.rect(screen, (75, 50, 26), qbox.inflate(-8, -8), 1, border_radius=9)
    pygame.draw.rect(screen, (29, 19, 11), qhead, border_radius=10)
    pygame.draw.rect(screen, (238, 181, 70), qhead, 2, border_radius=10)

    qtitle_font = pygame.font.SysFont("Georgia", 25, bold=True)
    qtitle = qtitle_font.render(f"PERTANYAAN {quiz_index + 1:02d}", True, (255, 232, 176))
    screen.blit(qtitle, qtitle.get_rect(center=(qhead.centerx, qhead.centery)))

    qfont = pygame.font.SysFont("Georgia", max(22, min(30, int(H * 0.040))), bold=False)
    q_lines = wrap_text(qfont, q["question"], qbox.w - 60)
    if len(q_lines) > 2:
        qfont = pygame.font.SysFont("Georgia", max(20, qfont.get_height() - 2))
        q_lines = wrap_text(qfont, q["question"], qbox.w - 60)[:2]
    total_h = len(q_lines) * qfont.get_height()
    yy = qbox.centery - total_h // 2
    for line in q_lines:
        qs = qfont.render(line, True, (255, 239, 204))
        screen.blit(qs, qs.get_rect(center=(qbox.centerx, yy + qfont.get_height() // 2)))
        yy += qfont.get_height()

    option_rects = quiz_option_layout(W, H, len(q["options"]))
    mouse_pos = logical_mouse()
    for idx, (r, option) in enumerate(zip(option_rects, q["options"])):
        is_selected = selected == idx
        correct = selected is not None and idx == q["answer"]
        wrong = selected == idx and idx != q["answer"]
        hover = selected is None and r.collidepoint(mouse_pos)
        _draw_quiz_answer_card(screen, r, idx + 1, option, text_font, is_selected, correct, wrong, hover)

    hint = small_font.render("Pilih jawaban dengan klik atau tekan 1, 2, 3, 4", True, (255, 226, 163))
    screen.blit(hint, hint.get_rect(center=(W // 2, H - 30)))
    back = pygame.Rect(34, H - 68, 205, 46)
    draw_gold_panel(screen, back, "KEMBALI", None, False)

    popup_button = None
    if selected is not None:
        popup_button = _draw_quiz_popup(screen, W, H, q, selected, quiz_index, text_font, small_font)
    return option_rects, back, popup_button

def draw_attack(screen, backgrounds, W, H, big_font, text_font, small_font, bima, arjuna, left_name, right_name, bima_attacking=False, arjuna_attacking=False):
    draw_background(screen, backgrounds, "ui_batik", W, H)
    top=pygame.Surface((W,86),pygame.SRCALPHA); top.fill((18,12,7,210)); screen.blit(top,(0,0))
    title=big_font.render("GESTURE ATTACK",True,(255,216,125)); screen.blit(title,(35,18))
    info=text_font.render(f"Pemain 1: {left_name}   |   Pemain 2: {right_name}",True,(235,225,205)); screen.blit(info,(W-540,28))
    pygame.draw.line(screen,(150,98,44),(W//2,115),(W//2,H-45),2)
    STYLE["halo"] = "dark"
    try:
        bima.draw(screen); arjuna.draw(screen)
    finally:
        STYLE["halo"] = "gold"
    if bima_attacking:
        fx=pygame.Surface((150,150),pygame.SRCALPHA); pygame.draw.circle(fx,(214,70,32,140),(75,75),55,5); screen.blit(fx,fx.get_rect(center=(bima.pos.x+75,bima.pos.y)))
        s=small_font.render("SERANG!",True,(170,34,18)); screen.blit(s,(bima.pos.x-55,bima.pos.y-245))
    if arjuna_attacking:
        fx=pygame.Surface((150,150),pygame.SRCALPHA); pygame.draw.circle(fx,(214,70,32,140),(75,75),55,5); screen.blit(fx,fx.get_rect(center=(arjuna.pos.x-75,arjuna.pos.y)))
        s=small_font.render("SERANG!",True,(170,34,18)); screen.blit(s,(arjuna.pos.x-55,arjuna.pos.y-245))
    panel=pygame.Surface((W-80,72),pygame.SRCALPHA); panel.fill((10,8,6,200)); screen.blit(panel,(40,H-95))
    help_s=small_font.render("TELAPAK = GERAK / SIAGA    •    KEPAL = SERANG    •    V = POV    •    C = GANTI KARAKTER    •    M = MENU    •    ESC = KELUAR",True,(245,235,215))
    screen.blit(help_s,help_s.get_rect(center=(W//2,H-59)))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", type=int, default=None)
    parser.add_argument("--projector", action="store_true")
    args = parser.parse_args()

    if args.camera is not None:
        CONFIG["window"]["camera_index"] = args.camera

    pygame.init()
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    except pygame.error as exc:
        print(f"[WARNING] Audio mixer gagal: {exc}")

    W = int(CONFIG["window"]["width"])
    H = int(CONFIG["window"]["height"])
    pygame.display.set_mode((W, H), pygame.RESIZABLE)
    screen = pygame.Surface((W, H))  # kanvas logis; ditampilkan lewat present_canvas()
    pygame.display.set_caption("Bima dan Arjuna – Janji di Tengah Hutan")
    clock = pygame.time.Clock()
    audio = Audio()
    backgrounds = load_backgrounds((W, H))
    validate_story_assets()
    audio.preload_all()

    camera_index = int(CONFIG["window"]["camera_index"])
    cam = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    # Keep the camera responsive: MediaPipe does not need a 1280x720 frame.
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    if not cam.isOpened():
        print(f"[WARNING] Kamera {camera_index} tidak tersedia. Program tetap berjalan tanpa tracking tangan.")
        cam = None

    detector = None
    try:
        import mediapipe as mp
        detector = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.55,
            min_tracking_confidence=0.55,
            model_complexity=1,
        )
    except Exception as exc:
        print(f"[WARNING] MediaPipe tidak siap: {exc}. Wayang tetap bisa dimainkan dengan tombol/otomatis.")

    puppet_cfg = CONFIG["puppet"]
    bima = make_puppet("bima_new.png", puppet_cfg["left_start_x"], puppet_cfg["left_start_y"], puppet_cfg["target_height"], puppet_cfg["left_offset_x"], puppet_cfg["left_offset_y"])
    arjuna = make_puppet("arjuna_new.png", puppet_cfg["right_start_x"], puppet_cfg["right_start_y"], puppet_cfg["target_height"], puppet_cfg["right_offset_x"], puppet_cfg["right_offset_y"])
    # Aset Bima baru menghadap kiri secara asli. Untuk tampilan story dan
    # posisi awal, Bima tetap menghadap ke kanan (ke arah Arjuna).
    bima.set_visual_facing(1, -1)
    # Arjuna menghadap kiri secara asli, sehingga tetap menghadap ke Bima.
    arjuna.set_visual_facing(-1, -1)
    bima_gesture = GestureStabilizer(int(CONFIG["gesture"]["required_frames"]))
    arjuna_gesture = GestureStabilizer(int(CONFIG["gesture"]["required_frames"]))
    attack_left_state = 1
    attack_right_state = 1
    attack_left_puppet = bima
    attack_right_puppet = arjuna

    def rebuild_attack_puppets():
        nonlocal attack_left_puppet, attack_right_puppet
        lc = CHARACTERS[flow.char_left_idx]
        rc = CHARACTERS[flow.char_right_idx]
        attack_left_puppet = make_puppet(lc["file"], 385, 470, puppet_cfg["target_height"], puppet_cfg["left_offset_x"], puppet_cfg["left_offset_y"])
        attack_right_puppet = make_puppet(rc["file"], 895, 470, puppet_cfg["target_height"], puppet_cfg["right_offset_x"], puppet_cfg["right_offset_y"])
        # Karakter kiri selalu menghadap ke tengah (kanan).
        # Karakter kanan selalu menghadap ke tengah (kiri).
        attack_left_puppet.set_visual_facing(1, lc.get("source_facing", 1))
        attack_right_puppet.set_visual_facing(-1, rc.get("source_facing", 1))


    flow = Flow()
    projector = args.projector
    fullscreen = False
    running = True
    camera_frame_counter = 0
    last_space_time = 0.0
    pov_mode = bool(CONFIG["window"].get("show_pov", True))
    latest_hand_result = None
    latest_camera_surface = None
    flow.settings_show_pov = pov_mode
    flow.settings_music = True

    speaker_font = pygame.font.SysFont("Arial", 34, bold=True)
    text_font = pygame.font.SysFont("Arial", 25)
    big_font = pygame.font.SysFont("Georgia", 58, bold=True)
    sub_font = pygame.font.SysFont("Georgia", 36, bold=True)
    small_font = pygame.font.SysFont("Arial", 20)

    def start_scene_narration():
        scene = STORY["scenes"][flow.scene_index]
        print(f"[NARRATION] Adegan {scene['id']} mulai: {scene['narration']}")
        play_voice(scene["narration"])

    def current_dialogue():
        scene = STORY["scenes"][flow.scene_index]
        return scene["dialogues"][flow.dialog_index]

    def play_dialogue():
        # Every dialogue item is [speaker, text, audio].
        dialogue = current_dialogue()
        if not isinstance(dialogue, (list, tuple)) or len(dialogue) != 3:
            raise ValueError(f"Format dialog harus [speaker, text, audio]: {dialogue!r}")
        speaker, text, audio_name = dialogue
        print(f"[DIALOGUE] Adegan {STORY['scenes'][flow.scene_index]['id']} | {speaker}: {text}")
        play_voice(audio_name)
        # IMPORTANT: every dialogue gets a fresh phase timer. Without this,
        # dialogue #2 inherited the timer from dialogue #1 and could be
        # considered finished immediately, skipping voices/dialogues.
        flow.phase_started = time.monotonic()

    def narration_text_for(audio_name, text):
        """Return the text exactly for the voice currently playing."""
        return text

    def play_voice(filename):
        ok = audio.play(filename)
        flow.played = True
        if not ok:
            # Do not silently skip a missing/broken voice.
            print(f"[ERROR] Voice gagal diputar: {filename}")
        return ok

    def after_pause_text():
        return AFTER_PAUSE_TEXT

    def opening_text_for_current_time():
        # Gunakan timestamp hasil jeda aktual rekaman, bukan pembagian
        # berdasarkan jumlah kata. Ini membuat teks tidak tertinggal dari suara.
        t = audio.elapsed()
        idx = len(OPENING_PAGES) - 1
        alpha = 255
        for i, (start, end) in enumerate(OPENING_TIMINGS):
            if t < end:
                idx = i
                local = max(0.0, t - start)
                alpha = 255 if local >= 0.06 else int(local / 0.06 * 255)
                break
        return OPENING_PAGES[idx], alpha, idx

    while running:
        now = time.monotonic()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = logical_pos(event.pos)
                if flow.phase == "menu":
                    # IMPORTANT: use the exact same responsive rectangles as draw_menu().
                    menu_hits = menu_button_layout(W, H)
                    for key,r in menu_hits:
                        if r.collidepoint(mx,my):
                            if key == "story": flow.enter("opening")
                            elif key == "attack": rebuild_attack_puppets(); flow.enter("attack")
                            elif key == "characters": flow.enter("characters")
                            elif key == "physical": flow.enter("physical_wayang")
                            elif key == "quiz":
                                flow.enter("quiz")
                                flow.quiz_index = 0
                                flow.quiz_score = 0
                                flow.quiz_selected = None
                                flow.quiz_finished = False
                                print("[QUIZ] Mulai kuis dari menu")
                            elif key == "settings": flow.enter("settings")
                            break
                elif flow.phase == "quiz" and flow.quiz_finished:
                    if pygame.Rect(34, H - 68, 205, 46).collidepoint(mx, my):
                        flow.enter("menu")
                elif flow.phase == "quiz" and not flow.quiz_finished:
                    back_rect = pygame.Rect(34, H - 68, 205, 46)
                    if back_rect.collidepoint(mx, my):
                        flow.enter("menu")
                    elif flow.quiz_selected is not None:
                        q = QUIZ_QUESTIONS[flow.quiz_index]
                        _, popup_button = quiz_popup_layout(W, H)
                        if popup_button.collidepoint(mx, my):
                            if flow.quiz_selected == q["answer"]:
                                if flow.quiz_index < len(QUIZ_QUESTIONS) - 1:
                                    flow.quiz_index += 1
                                    flow.quiz_selected = None
                                    flow.phase_started = time.monotonic()
                                else:
                                    flow.quiz_finished = True
                                    flow.phase_started = time.monotonic()
                                    print(f"[QUIZ] Selesai: {flow.quiz_score}/{len(QUIZ_QUESTIONS)}")
                            else:
                                flow.quiz_selected = None
                                flow.phase_started = time.monotonic()
                    else:
                        q = QUIZ_QUESTIONS[flow.quiz_index]
                        for idx, option_rect in enumerate(quiz_option_layout(W, H, len(q["options"]))):
                            if option_rect.collidepoint(mx, my):
                                flow.quiz_selected = idx
                                if idx == q["answer"]:
                                    flow.quiz_score += 1
                                    print(f"[QUIZ] Soal {flow.quiz_index + 1}: BENAR")
                                else:
                                    print(f"[QUIZ] Soal {flow.quiz_index + 1}: SALAH")
                                flow.phase_started = time.monotonic()
                                break
                elif flow.phase == "characters":
                    cards, back, slot_tabs = draw_character_menu(screen, backgrounds, W, H, big_font, sub_font, text_font, small_font, flow.char_left_idx, flow.char_right_idx, flow.character_slot)
                    if back.collidepoint(mx,my):
                        flow.enter("menu")
                    else:
                        picked = False
                        for idx,r in cards:
                            if r.collidepoint(mx,my):
                                if flow.character_slot == 0: flow.char_left_idx = idx
                                else: flow.char_right_idx = idx
                                rebuild_attack_puppets()
                                picked = True
                                break
                        if not picked:
                            for si,r in slot_tabs:
                                if r.collidepoint(mx,my):
                                    flow.character_slot = si
                                    break
                elif flow.phase == "settings":
                    rects, back = draw_settings(screen, backgrounds, W, H, big_font, text_font, small_font, pov_mode, flow.settings_music)
                    if back.collidepoint(mx,my):
                        flow.enter("menu")
                    elif rects[0].collidepoint(mx,my):
                        pov_mode = not pov_mode; flow.settings_show_pov = pov_mode
                        if not pov_mode: update_pov_window(None,None,False)
                    elif rects[1].collidepoint(mx,my):
                        flow.settings_music = not flow.settings_music
                elif flow.phase == "physical_wayang":
                    phys = get_phys_controller()
                    if hasattr(flow, '_phys_rects') and flow._phys_rects:
                        pr = flow._phys_rects
                        if pr.get("back") and pr["back"].collidepoint(mx, my):
                            phys.disconnect_all()
                            flow.enter("menu")
                        elif pr.get("start") and pr["start"].collidepoint(mx, my):
                            phys.running = not phys.running
                            if phys.running:
                                print("[FISIK] Pertunjukan dimulai")
                            else:
                                print("[FISIK] Pertunjukan dihentikan")
                        elif pr.get("connect_nano") and pr["connect_nano"].collidepoint(mx, my):
                            if phys.nano_connected:
                                phys.disconnect_nano()
                            else:
                                phys.connect_nano()
                        elif pr.get("cycle_nano_port") and pr["cycle_nano_port"].collidepoint(mx, my):
                            phys.cycle_nano_port()
                        elif pr.get("test_servo") and pr["test_servo"].collidepoint(mx, my):
                            phys.test_servo()
                        elif pr.get("connect_grbl") and pr["connect_grbl"].collidepoint(mx, my):
                            if phys.grbl_connected:
                                phys.disconnect_grbl()
                            else:
                                phys.connect_grbl()
                        elif pr.get("cycle_grbl_port") and pr["cycle_grbl_port"].collidepoint(mx, my):
                            phys.cycle_grbl_port()
                        elif pr.get("home_grbl") and pr["home_grbl"].collidepoint(mx, my):
                            phys.home_grbl()
                        elif pr.get("unlock_grbl") and pr["unlock_grbl"].collidepoint(mx, my):
                            phys.unlock_grbl()
                        elif pr.get("speed_bar") and pr["speed_bar"].collidepoint(mx, my):
                            bar = pr["speed_bar"]
                            pct = max(0.0, min(1.0, (mx - bar.x) / max(1, bar.w)))
                            phys.set_speed(50 + pct * 1150)
                        elif pr.get("speed_dec_50") and pr["speed_dec_50"].collidepoint(mx, my):
                            phys.set_speed(phys.feedrate - 50)
                        elif pr.get("speed_dec_10") and pr["speed_dec_10"].collidepoint(mx, my):
                            phys.set_speed(phys.feedrate - 10)
                        elif pr.get("speed_inc_10") and pr["speed_inc_10"].collidepoint(mx, my):
                            phys.set_speed(phys.feedrate + 10)
                        elif pr.get("speed_inc_50") and pr["speed_inc_50"].collidepoint(mx, my):
                            phys.set_speed(phys.feedrate + 50)
                        elif pr.get("toggle_fullscreen") and pr["toggle_fullscreen"].collidepoint(mx, my):
                            flow.phys_fullscreen_pov = not getattr(flow, "phys_fullscreen_pov", False)
                            print(f"[FISIK] Fullscreen POV: {'AKTIF' if flow.phys_fullscreen_pov else 'NONAKTIF'}")
                        elif pr.get("jog_x_minus") and pr["jog_x_minus"].collidepoint(mx, my):
                            phys.jog_step("X", -10)
                        elif pr.get("jog_x_plus") and pr["jog_x_plus"].collidepoint(mx, my):
                            phys.jog_step("X", +10)
                        elif pr.get("jog_y_minus") and pr["jog_y_minus"].collidepoint(mx, my):
                            phys.jog_step("Y", -10)
                        elif pr.get("jog_y_plus") and pr["jog_y_plus"].collidepoint(mx, my):
                            phys.jog_step("Y", +10)
                        elif pr.get("toggle_stepper_mode") and pr["toggle_stepper_mode"].collidepoint(mx, my):
                            phys.stepper_mode = "2_hands" if phys.stepper_mode == "smart" else "smart"
                            print(f"[FISIK] Mode stepper: {phys.stepper_mode}")
                        elif pr.get("defaults") and pr["defaults"].collidepoint(mx, my):
                            phys.x_min = 0.0; phys.x_max = 200.0
                            phys.y_min = 0.0; phys.y_max = 200.0
                            phys.feedrate = 300; phys.servo_angle = 25
                            phys.interval_kirim = 0.08; phys.deadband = 0.8
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if flow.phase in ("menu", "characters", "settings", "physical_wayang"):
                        if flow.phase == "menu":
                            running = False
                        elif flow.phase == "physical_wayang":
                            get_phys_controller().disconnect_all()
                            flow.enter("menu")
                        else:
                            flow.enter("menu")
                    else:
                        running = False
                elif flow.phase == "menu" and event.key == pygame.K_1:
                    flow.enter("opening")
                elif flow.phase == "menu" and event.key == pygame.K_2:
                    rebuild_attack_puppets(); flow.enter("attack")
                elif flow.phase == "menu" and event.key == pygame.K_3:
                    flow.enter("characters")
                elif flow.phase == "menu" and event.key == pygame.K_4:
                    flow.enter("physical_wayang")
                elif flow.phase == "menu" and event.key == pygame.K_5:
                    flow.enter("quiz")
                    flow.quiz_index = 0
                    flow.quiz_score = 0
                    flow.quiz_selected = None
                    flow.quiz_finished = False
                    print("[QUIZ] Mulai kuis dari menu")
                elif flow.phase == "menu" and event.key == pygame.K_6:
                    flow.enter("settings")
                elif flow.phase == "attack" and event.key == pygame.K_m:
                    flow.enter("menu")
                elif flow.phase == "physical_wayang":
                    phys = get_phys_controller()
                    if event.key in (pygame.K_ESCAPE, pygame.K_m):
                        phys.disconnect_all()
                        flow.enter("menu")
                    elif event.key == pygame.K_SPACE:
                        phys.running = not phys.running
                        print(f"[FISIK] Pertunjukan {'dimulai' if phys.running else 'dihentikan'}")
                    elif event.key in (pygame.K_UP, pygame.K_RIGHT):
                        phys.set_speed(phys.feedrate + 50)
                    elif event.key in (pygame.K_DOWN, pygame.K_LEFT):
                        phys.set_speed(phys.feedrate - 50)
                    elif event.key == pygame.K_f:
                        flow.phys_fullscreen_pov = not getattr(flow, "phys_fullscreen_pov", False)
                        print(f"[FISIK] Fullscreen POV (F): {'AKTIF' if flow.phys_fullscreen_pov else 'NONAKTIF'}")
                    elif event.key == pygame.K_h:
                        phys.home_grbl()
                    elif event.key == pygame.K_t:
                        phys.test_servo()
                elif flow.phase == "attack" and event.key == pygame.K_c:
                    flow.enter("characters")
                elif flow.phase == "characters" and event.key == pygame.K_1:
                    flow.character_slot = 0
                elif flow.phase == "characters" and event.key == pygame.K_2:
                    flow.character_slot = 1
                elif flow.phase == "characters" and event.key == pygame.K_ESCAPE:
                    flow.enter("menu")
                elif flow.phase == "settings" and event.key == pygame.K_ESCAPE:
                    flow.enter("menu")
                elif event.key == pygame.K_F11:
                    fullscreen = not fullscreen
                    if fullscreen:
                        pygame.display.set_mode((0, 0), pygame.FULLSCREEN)  # resolusi asli monitor
                    else:
                        pygame.display.set_mode((W, H), pygame.RESIZABLE)
                elif event.key == pygame.K_p:
                    projector = not projector
                elif event.key == pygame.K_v:
                    pov_mode = not pov_mode
                    if not pov_mode:
                        update_pov_window(None, None, False)
                    print(f"[POV] {'AKTIF' if pov_mode else 'NONAKTIF'} - jendela terpisah")
                elif event.key == pygame.K_SPACE and flow.phase == "dialogue" and (time.monotonic() - last_space_time) > 0.30:
                    last_space_time = time.monotonic()
                    # SPACE is only an explicit "continue" after the current
                    # voice has finished. It can never skip/cut a voice.
                    if audio.done():
                        scene = STORY["scenes"][flow.scene_index]
                        if flow.dialog_index < len(scene["dialogues"]) - 1:
                            flow.dialog_index += 1
                            play_dialogue()
                        elif flow.scene_index < len(STORY["scenes"]) - 1:
                            flow.scene_index += 1
                            print(f"[SCENE] Masuk adegan {STORY['scenes'][flow.scene_index]['id']}")
                            flow.enter("scene_transition")
                        else:
                            flow.enter("final_voice")
                elif flow.phase == "quiz" and event.key == pygame.K_m:
                    flow.enter("menu")
                elif flow.phase == "quiz" and event.key == pygame.K_ESCAPE:
                    flow.enter("menu")
                elif flow.phase == "quiz" and not flow.quiz_finished:
                    q = QUIZ_QUESTIONS[flow.quiz_index]
                    if flow.quiz_selected is not None and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        if flow.quiz_selected == q["answer"]:
                            if flow.quiz_index < len(QUIZ_QUESTIONS) - 1:
                                flow.quiz_index += 1
                                flow.quiz_selected = None
                                flow.phase_started = time.monotonic()
                            else:
                                flow.quiz_finished = True
                                flow.phase_started = time.monotonic()
                        else:
                            flow.quiz_selected = None
                            flow.phase_started = time.monotonic()
                    elif flow.quiz_selected is None and event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                        choice = event.key - pygame.K_1
                        flow.quiz_selected = choice
                        if choice == q["answer"]:
                            flow.quiz_score += 1
                            print(f"[QUIZ] Soal {flow.quiz_index + 1}: BENAR")
                        else:
                            print(f"[QUIZ] Soal {flow.quiz_index + 1}: SALAH")
                        flow.phase_started = time.monotonic()

                # N intentionally does nothing now. The previous build could
                # accidentally skip narration/dialogue when N was pressed.

        # Hand tracking is isolated from the story flow so camera errors cannot
        # stop the story.
        if cam is not None and detector is not None:
            ok, frame = cam.read()
            camera_frame_counter += 1
            if ok and camera_frame_counter % 2 == 0:
                try:
                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    result = detector.process(rgb)
                    latest_hand_result = result
                    if pov_mode and flow.phase in ("attack", "scene_narration", "dialogue"):
                        update_pov_window(frame, result, True)
                    else:
                        update_pov_window(None, None, False)
                    hands = detect_hands(result, W, H)
                    left_hand = hands.get("Left")
                    right_hand = hands.get("Right")
                    unknown = hands.get("Unknown")
                    if flow.phase == "physical_wayang":
                        if getattr(flow, "phys_fullscreen_pov", False):
                            # Fullscreen POV: resolusi penuh untuk kamera
                            latest_camera_surface = make_camera_preview(frame, result, (W, H))
                        else:
                            latest_camera_surface = make_camera_preview(frame, result, (520, 390))
                        phys = get_phys_controller()
                        if phys.running:
                            phys.process_hands(hands, W, H)
                    elif flow.phase == "attack":
                        lh = left_hand or (unknown if not right_hand else None)
                        if lh:
                            gs = bima_gesture.update(lh["gesture"])
                            attack_left_state = gs
                            attack_left_puppet.update_hand(lh, float(puppet_cfg["smooth"]))
                            attack_left_puppet.set_visual_facing(1, CHARACTERS[flow.char_left_idx].get("source_facing", 1))
                            if gs == -1:
                                attack_left_puppet.target.x += 75
                        if right_hand:
                            gs = arjuna_gesture.update(right_hand["gesture"])
                            attack_right_state = gs
                            attack_right_puppet.update_hand(right_hand, float(puppet_cfg["smooth"]))
                            attack_right_puppet.set_visual_facing(-1, CHARACTERS[flow.char_right_idx].get("source_facing", 1))
                            if gs == -1:
                                attack_right_puppet.target.x -= 75
                    else:
                        if left_hand:
                            bima.update_hand(left_hand, float(puppet_cfg["smooth"]))
                            bima.set_facing(bima_gesture.update(left_hand["gesture"]))
                        elif unknown and not right_hand:
                            bima.update_hand(unknown, float(puppet_cfg["smooth"]))
                            bima.set_facing(bima_gesture.update(unknown["gesture"]))
                        if right_hand:
                            arjuna.update_hand(right_hand, float(puppet_cfg["smooth"]))
                            arjuna.set_facing(arjuna_gesture.update(right_hand["gesture"]))
                except Exception as exc:
                    print(f"[WARNING] Hand tracking dilewati: {exc}")
        
        # ---------------- FLOW ----------------
        if flow.phase == "menu":
            # Musik khusus menu: backsound gamelan berjalan loop dan tidak
            # mengganggu audio Story. Musik akan dimulai sekali saat menu aktif.
            if flow.settings_music and safe_sound_file("menu_gamelan.mp3"):
                if not pygame.mixer.music.get_busy() or not flow.menu_music_started:
                    pygame.mixer.music.load(str(AUDIO / "menu_gamelan.mp3"))
                    pygame.mixer.music.set_volume(0.26)
                    pygame.mixer.music.play(-1)
                    flow.menu_music_started = True
            elif not flow.settings_music and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                flow.menu_music_started = False
        elif flow.phase == "characters":
            if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
            flow.menu_music_started = False
        elif flow.phase == "settings":
            if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
            flow.menu_music_started = False
        elif flow.phase == "physical_wayang":
            if pygame.mixer.music.get_busy(): pygame.mixer.music.stop()
            flow.menu_music_started = False
        elif flow.phase == "attack":
            flow.menu_music_started = False
            # Free-play mode: no story audio, no narration, no automatic scene changes.
            if flow.settings_music and not pygame.mixer.music.get_busy() and safe_sound_file("03_musik_pembuka.mp3"):
                pygame.mixer.music.load(str(AUDIO / "03_musik_pembuka.mp3")); pygame.mixer.music.set_volume(0.28); pygame.mixer.music.play(-1)
        elif flow.phase == "opening":
            if not flow.played:
                play_voice("01_pembukaan.mp3")
            if flow.played and audio.done():
                audio.stop()
                flow.enter("pause_after_opening")

        elif flow.phase == "pause_after_opening":
            if flow.elapsed() >= 1.0:
                flow.enter("after_pause_voice")

        elif flow.phase == "after_pause_voice":
            if not flow.played:
                play_voice("02_setelah_jeda.mp3")
            if flow.played and audio.done():
                audio.stop()
                if not flow.music_started and safe_sound_file("03_musik_pembuka.mp3"):
                    pygame.mixer.music.load(str(AUDIO / "03_musik_pembuka.mp3"))
                    pygame.mixer.music.set_volume(0.0)
                    pygame.mixer.music.play(-1)
                    flow.music_started = True
                flow.enter("mari")

        elif flow.phase == "mari":
            if flow.music_started:
                pygame.mixer.music.set_volume(min(0.50, flow.elapsed() / 2.5 * 0.50))
            if not flow.played:
                play_voice("04_mari_kita_ikuti.mp3")
            if flow.played and audio.done():
                audio.stop()
                flow.enter("title_fade")
                flow.title_started = time.monotonic()

        elif flow.phase == "title_fade":
            # Darken the scene first; title enters softly during the darkening.
            duration = 2.8
            if flow.elapsed() >= duration:
                flow.enter("title_voice_1")

        elif flow.phase == "title_voice_1":
            if not flow.played:
                play_voice("05_judul_subjudul.mp3")
            if flow.played and audio.done():
                audio.stop()
                flow.enter("title_voice_2")

        elif flow.phase == "title_voice_2":
            if not flow.played:
                play_voice("06_judul_utama.mp3")
            if flow.played and audio.done():
                audio.stop()
                flow.enter("title_hold")

        elif flow.phase == "title_hold":
            if flow.elapsed() >= 2.0:
                if flow.music_started:
                    pygame.mixer.music.fadeout(1400)
                flow.enter("scene_narration")

        elif flow.phase == "scene_transition":
            # The previous voice has already finished before this phase is
            # entered. Keep a short visual transition, then start the next
            # scene narration. Never play/cut audio during the transition.
            if flow.elapsed() >= 0.65:
                flow.enter("scene_narration")

        elif flow.phase == "scene_narration":
            if not flow.played:
                start_scene_narration()
            # Use the measured Sound length as the authoritative end point.
            # This prevents a mixer/channel timing race from advancing early.
            narration_done = audio.done()
            if narration_done:
                audio.stop()
                # Give the last narration frame a brief visual hold before the
                # first character voice. This prevents the narration and first
                # dialogue from visually colliding at the boundary.
                flow.dialog_index = 0
                flow.enter("dialogue_start")

        elif flow.phase == "dialogue_start":
            if flow.elapsed() >= 0.28:
                flow.enter("dialogue")
                play_dialogue()

        elif flow.phase == "dialogue":
            scene = STORY["scenes"][flow.scene_index]
            # Each dialogue waits for its own measured audio length. We do not
            # use the old fixed 5.5-second setting.
            dialogue_done = flow.played and audio.done()
            if dialogue_done:
                audio.stop()
                if flow.dialog_index < len(scene["dialogues"]) - 1:
                    flow.dialog_index += 1
                    play_dialogue()
                elif flow.scene_index < len(STORY["scenes"]) - 1:
                    flow.scene_index += 1
                    print(f"[SCENE] Masuk adegan {STORY['scenes'][flow.scene_index]['id']}")
                    flow.enter("scene_transition")
                else:
                    flow.enter("final_voice")

        elif flow.phase == "final_voice":
            if not flow.played:
                play_voice("12_akhir_cerita.mp3")
            if flow.played and audio.done():
                audio.stop()
                flow.enter("moral_pause")

        elif flow.phase == "moral_pause":
            if flow.elapsed() >= 1.2:
                flow.enter("moral")

        elif flow.phase == "moral":
            if not flow.played:
                play_voice("13_pesan_moral.mp3")
            if flow.played and audio.done():
                audio.stop()
                flow.enter("closing_voice")

        elif flow.phase == "closing_voice":
            if not flow.played:
                play_voice("14_penutup.mp3")
            if flow.played and audio.done():
                audio.stop()
                flow.enter("ending")

        elif flow.phase == "ending":
            if flow.elapsed() >= 8.0:
                flow.enter("quiz")
                flow.quiz_index = 0
                flow.quiz_score = 0
                flow.quiz_selected = None
                flow.quiz_finished = False
                print("[QUIZ] Mulai kuis penonton")

        elif flow.phase == "quiz":
            # Feedback popup stays open until the user chooses Lanjut/Ulangi.
            pass

        # ---------------- DRAW ----------------
        if flow.phase == "menu":
            mouse_x, mouse_y = logical_mouse()
            hover = next((key for key, r in menu_button_layout(W, H) if r.collidepoint(mouse_x, mouse_y)), None)
            draw_menu(screen, backgrounds, W, H, big_font, sub_font, text_font, small_font, hover)
        elif flow.phase == "characters":
            draw_character_menu(screen, backgrounds, W, H, big_font, sub_font, text_font, small_font, flow.char_left_idx, flow.char_right_idx, flow.character_slot)
        elif flow.phase == "settings":
            draw_settings(screen, backgrounds, W, H, big_font, text_font, small_font, pov_mode, flow.settings_music)
        elif flow.phase == "physical_wayang":
            flow._phys_rects = draw_physical_wayang_ui(
                screen, backgrounds, W, H, big_font, text_font, small_font,
                camera_surface=latest_camera_surface, ctrl=get_phys_controller(),
                detector_ready=(detector is not None),
                fullscreen_pov=getattr(flow, "phys_fullscreen_pov", False)
            )
        elif flow.phase == "attack":
            draw_attack(screen, backgrounds, W, H, big_font, text_font, small_font, attack_left_puppet, attack_right_puppet, CHARACTERS[flow.char_left_idx]["name"], CHARACTERS[flow.char_right_idx]["name"], attack_left_state == -1, attack_right_state == -1)
        elif flow.phase in ("opening", "pause_after_opening", "after_pause_voice", "mari", "title_fade", "title_voice_1", "title_voice_2", "title_hold", "scene_transition"):
            transition_bg = "hutan_sore"
            if flow.phase == "scene_transition" and 0 <= flow.scene_index < len(STORY["scenes"]):
                transition_bg = STORY["scenes"][flow.scene_index]["background"]
            draw_background(screen, backgrounds, transition_bg, W, H)
            if flow.phase not in ("title_fade", "title_voice_1", "title_voice_2", "title_hold"):
                bima.draw_at(screen, (410, 470), 0.82)
                arjuna.draw_at(screen, (870, 470), 0.82)
            if flow.phase == "opening":
                opening_text, opening_alpha, _ = opening_text_for_current_time()
                # Gambar subtitle pembukaan langsung; tidak menjalankan lagi
                # sentence scheduler di dalam draw_narration.
                panel_h = 165
                panel = pygame.Surface((W - 100, panel_h), pygame.SRCALPHA)
                panel.fill((0, 0, 0, int(190 * max(0.82, opening_alpha / 255))))
                screen.blit(panel, (50, H - panel_h - 25))
                label = pygame.font.SysFont("Arial", 28, bold=True).render("Narator", True, (255, 235, 170))
                label.set_alpha(opening_alpha)
                screen.blit(label, (80, H - panel_h - 8))
                y = H - panel_h + 36
                for line in wrap_text(text_font, opening_text, W - 160)[:3]:
                    surf = text_font.render(line, True, (255, 255, 255))
                    surf.set_alpha(opening_alpha)
                    screen.blit(surf, (80, y))
                    y += 32
            elif flow.phase == "after_pause_voice":
                draw_narration(screen, AFTER_PAUSE_TEXT, W, H, text_font, audio.elapsed(), audio.current_length, "Narator", audio.current_lead, audio.current_tail)
            elif flow.phase in ("title_fade", "title_voice_1", "title_voice_2", "title_hold"):
                p = min(1.0, flow.elapsed() / 2.8) if flow.phase == "title_fade" else 1.0
                fade_overlay(screen, W, H, 235 * p)
                draw_title(screen, W, H, big_font, sub_font, p)

        elif flow.phase in ("scene_narration", "dialogue_start", "dialogue"):
            scene = STORY["scenes"][flow.scene_index]
            draw_background(screen, backgrounds, scene["background"], W, H)
            bima.draw(screen)
            arjuna.draw(screen)
            if flow.phase == "scene_narration":
                draw_narration(screen, scene.get("narration_text", ""), W, H, text_font, audio.elapsed(), audio.current_length, "Narator", audio.current_lead, audio.current_tail, NARRATION_TIMINGS.get(scene.get("narration")))
            elif flow.phase == "dialogue_start":
                # Keep the final narration frame visible during the short
                # handoff instead of flashing an empty panel.
                last_sentence = split_sentences(scene.get("narration_text", ""))[-1:]
                draw_narration(screen, " ".join(last_sentence), W, H, text_font, 1.0, 1.0, "Narator", 0.0, 0.0)
            else:
                speaker, text, _ = scene["dialogues"][flow.dialog_index]
                draw_dialogue(screen, speaker, text, W, H, speaker_font, text_font, audio.elapsed(), audio.current_length, audio.current_lead, audio.current_tail)

        elif flow.phase in ("final_voice", "moral_pause", "moral", "closing_voice"):
            draw_background(screen, backgrounds, "hutan_sore", W, H)
            bima.draw(screen)
            arjuna.draw(screen)
            if flow.phase == "final_voice":
                draw_narration(screen, FINAL_STORY_TEXT, W, H, text_font, audio.elapsed(), audio.current_length, "Narator", audio.current_lead, audio.current_tail, NARRATION_TIMINGS.get("12_akhir_cerita.mp3"))
            elif flow.phase == "moral":
                draw_narration(screen, MORAL_TEXT, W, H, text_font, audio.elapsed(), audio.current_length, "Pesan Moral", audio.current_lead, audio.current_tail, NARRATION_TIMINGS.get("13_pesan_moral.mp3"))
            elif flow.phase == "closing_voice":
                draw_narration(screen, CLOSING_TEXT, W, H, text_font, audio.elapsed(), audio.current_length, "Penutup", audio.current_lead, audio.current_tail, NARRATION_TIMINGS.get("14_penutup.mp3"))

        elif flow.phase == "ending":
            draw_background(screen, backgrounds, "hutan_sore", W, H)
            t = min(1.0, flow.elapsed() / 6.0)
            scale = 1.0 - 0.78 * t
            y = 455 - 100 * t
            x1 = 370 + 175 * t
            x2 = 910 - 175 * t
            bima.draw_at(screen, (x1, y), scale)
            arjuna.draw_at(screen, (x2, y), scale)
            if not flow.music_started:
                if safe_sound_file("03_musik_pembuka.mp3"):
                    pygame.mixer.music.load(str(AUDIO / "03_musik_pembuka.mp3"))
                    pygame.mixer.music.set_volume(0.35)
                    pygame.mixer.music.play(-1)
                flow.music_started = True
            if t > 0.55:
                pygame.mixer.music.set_volume(max(0, 0.35 - (t - 0.55) * 0.7))
            if t > 0.70:
                fade_overlay(screen, W, H, (t - 0.70) / 0.30 * 255)
            if t > 0.90:
                alpha = int(min(255, (t - 0.90) / 0.10 * 255))
                msg = text_font.render(ENDING_TEXT, True, (255, 255, 255))
                msg.set_alpha(alpha)
                screen.blit(msg, msg.get_rect(center=(W // 2, H // 2)))
                tamat = sub_font.render("TAMAT", True, (255, 245, 210))
                tamat.set_alpha(alpha)
                screen.blit(tamat, tamat.get_rect(center=(W // 2, H // 2 + 70)))

        elif flow.phase == "quiz":
            draw_quiz_ui(
                screen, backgrounds, W, H, big_font, sub_font, text_font, small_font,
                flow.quiz_index, flow.quiz_score, flow.quiz_selected, flow.quiz_finished
            )

        elif flow.phase == "done":
            screen.fill((0, 0, 0))
            msg = sub_font.render("TAMAT", True, (255, 255, 255))
            screen.blit(msg, msg.get_rect(center=(W // 2, H // 2)))

        if not projector and flow.phase in ("scene_narration", "dialogue"):
            hint = small_font.render(
                "✊ mengepal = kiri | 🖐 telapak = kanan | SPACE = lanjut setelah suara selesai | V = buka/tutup jendela POV | F11 = fullscreen | ESC = keluar",
                True, (255, 255, 255),
            )
            screen.blit(hint, (18, 18))

        present_canvas(screen)
        clock.tick(30)

    audio.stop()
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass
    if detector is not None:
        detector.close()
    if cam is not None:
        cam.release()
    try:
        cv2.destroyWindow("POV Tangan - Live")
        cv2.destroyAllWindows()
    except Exception:
        pass
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("\nProgram berhenti karena error. Tekan ENTER untuk menutup terminal.")
        try:
            input()
        except EOFError:
            pass
