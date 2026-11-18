"""Disco Roller Runner: endless runner numa pista de roller disco dos anos 70.

Controles:
  Teclado: setas ou A/D trocam de faixa, ESPAÇO/seta pra cima/W pula, ENTER inicia.
  P ou ESC pausa, M liga/desliga o som.
  Mouse/toque: lado esquerdo da tela vai para a esquerda, lado direito para a
  direita, meio da tela pula.

Instalar e rodar:
  pip install pygame-ce numpy
  python disco_roller.py

As 3 músicas são sintetizadas pelo próprio código (sem arquivos de áudio),
então não há problema de licença.
"""
import asyncio
import math
import random

import numpy as np
import pygame

W, H = 480, 720
SR = 22050
LANES = [W * 0.2, W * 0.5, W * 0.8]
PLAYER_Y = 590
LEVEL_TIME = 30.0  # segundos por fase
SWERVE_CHANCE = (0.10, 0.25, 0.40, 0.50, 0.30, 0.45, 0.55)  # chance de um dançarino trocar de faixa, por fase
SWERVE_Y = 0  # altura da tela em que o dançarino de branco começa a avisar
SWERVE_WARN = 0.35  # segundos de aviso piscando antes de se mexer
SWERVE_SPEED = 420  # velocidade lateral (pixels por segundo)

LEVELS = [
    {"name": "Pista Clássica", "bpm": 110, "root": 55.00, "prog": [0, 0, 5, 7],
     "bg": (22, 4, 38), "tiles": ((130, 30, 170), (80, 12, 120)),
     "lights": ((255, 90, 200), (255, 220, 90)), "density": 0.55},
    {"name": "Neon Club", "bpm": 120, "root": 61.74, "prog": [0, 3, 5, 3],
     "bg": (4, 14, 40), "tiles": ((20, 150, 200), (10, 70, 130)),
     "lights": ((80, 255, 255), (255, 80, 220)), "density": 0.70},
    {"name": "Bola de Espelhos", "bpm": 130, "root": 65.41, "prog": [0, 5, 7, 5],
     "bg": (40, 10, 6), "tiles": ((230, 160, 30), (170, 60, 20)),
     "lights": ((255, 240, 150), (255, 70, 70)), "density": 0.85},
    {"name": "Space Disco", "bpm": 140, "root": 73.42, "prog": [0, 7, 5, 3],
     "bg": (6, 4, 24), "tiles": ((70, 30, 160), (22, 10, 72)),
     "lights": ((120, 255, 255), (255, 120, 255)), "density": 0.95,
     "stars": True, "sparkle": True},
    {"name": "Calçadão ao Pôr do Sol", "bpm": 115, "root": 58.27, "prog": [0, 5, 3, 7],
     "bg": (60, 20, 50), "tiles": ((255, 150, 90), (214, 84, 112)),
     "lights": ((255, 210, 120), (255, 120, 170)), "density": 0.75, "sun": True},
    {"name": "Boate de Gelo", "bpm": 125, "root": 69.30, "prog": [0, 3, 7, 10],
     "bg": (6, 24, 44), "tiles": ((90, 160, 210), (40, 90, 150)),
     "lights": ((255, 255, 255), (150, 220, 255)), "density": 0.90, "snow": True},
    {"name": "Carnaval 70", "bpm": 150, "root": 82.41, "prog": [0, 7, 0, 5],
     "bg": (0, 40, 24), "tiles": ((0, 130, 60), (0, 70, 140)),
     "lights": ((255, 223, 0), (255, 255, 255)), "density": 1.0,
     "confetti": True, "perc": True},
]
_rng = random.Random(7)  # semente fixa: as estrelas ficam sempre nos mesmos lugares
STARS = [(_rng.uniform(0, W), _rng.uniform(0, H), i * 0.7) for i in range(45)]
_rng2 = random.Random(11)
SNOW = [(_rng2.uniform(0, W), _rng2.uniform(0, H), _rng2.uniform(40, 110), 1 + i % 3, i * 0.9)
        for i in range(60)]
CONFETTI_COLORS = ((255, 223, 0), (255, 255, 255), (255, 90, 90), (120, 220, 255), (255, 150, 0))
CONFETTI = [(_rng2.uniform(0, W), _rng2.uniform(0, H), _rng2.uniform(90, 200),
             _rng2.choice(CONFETTI_COLORS), i * 0.5) for i in range(70)]
DANCER_COLORS = [(255, 70, 120), (80, 220, 255), (255, 200, 40), (140, 255, 120), (200, 120, 255)]


# ---------------------------------------------------------------- música ----
def _kick():
    t = np.arange(int(SR * 0.2)) / SR
    freq = 40 + 110 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 16) * 0.9


def _hat():
    n = int(SR * 0.06)
    t = np.arange(n) / SR
    return np.random.uniform(-1, 1, n) * np.exp(-t * 80) * 0.25


def _note(freq, dur, kind, vol, decay):
    t = np.arange(int(SR * dur)) / SR
    phase = (t * freq) % 1.0
    wave = (2 * phase - 1) if kind == "saw" else np.where(phase < 0.5, 1.0, -1.0)
    return wave * np.exp(-t * decay) * vol


def make_track(level):
    """Gera um loop de 16 tempos: bumbo, chimbal, baixo em oitavas e acordes."""
    bpm, root, prog = level["bpm"], level["root"], level["prog"]
    beat = 60.0 / bpm
    total = int(SR * beat * 16)
    buf = np.zeros(total)

    def put(sig, when):
        i = int(when * SR)
        if i >= total:
            return
        j = min(total, i + len(sig))
        buf[i:j] += sig[: j - i]

    kick, hat = _kick(), _hat()
    for b in range(16):
        put(kick, b * beat)
        put(hat, b * beat + beat / 2)
    for bar in range(4):
        semis = prog[bar]
        for step in range(8):  # baixo "disco": oitavas alternadas
            octave = 12 if step % 2 else 0
            freq = root * 2 ** ((semis + octave) / 12)
            put(_note(freq, beat / 2, "saw", 0.22, 7), (bar * 4 + step / 2) * beat)
        for beat_in_bar in (1, 3):  # acordes no contratempo
            for third in (0, 3, 7):
                freq = root * 4 * 2 ** ((semis + third) / 12)
                put(_note(freq, beat * 0.4, "square", 0.07, 9),
                    (bar * 4 + beat_in_bar + 0.5) * beat)
    if level.get("perc"):  # chocalho em todas as semicolcheias (batida de samba)
        for step in range(64):
            put(hat * 0.7, step * beat / 4)
    if level.get("sparkle"):  # notas agudas em semicolcheias (escala pentatônica)
        for step in range(64):
            freq = root * 8 * 2 ** ((0, 3, 5, 7, 10)[step % 5] / 12)
            put(_note(freq, beat / 4, "square", 0.05, 14), step * beat / 4)
    buf = buf / max(1e-9, np.max(np.abs(buf))) * 0.85
    pcm = (buf * 32767).astype(np.int16)
    stereo = np.ascontiguousarray(np.column_stack((pcm, pcm)))
    return pygame.sndarray.make_sound(stereo)


# --------------------------------------------------------- efeitos sonoros ----
def _sweep(f0, f1, dur, vol=0.4, kind="sine"):
    """Tom que desliza de f0 a f1 Hz, com volume caindo até zero."""
    n = int(SR * dur)
    phase = np.cumsum(np.linspace(f0, f1, n)) / SR
    wave = np.sin(2 * np.pi * phase) if kind == "sine" else np.where(phase % 1.0 < 0.5, 1.0, -1.0)
    return wave * np.linspace(1, 0, n) ** 1.5 * vol


def _noise(dur, vol=0.4):
    n = int(SR * dur)
    t = np.arange(n) / SR
    return np.random.uniform(-1, 1, n) * np.exp(-t * (6 / dur)) * vol


def _to_sound(buf):
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    return pygame.sndarray.make_sound(np.ascontiguousarray(np.column_stack((pcm, pcm))))


def make_sfx():
    """Efeitos curtos do jogo, todos gerados por código."""
    def arpeggio(freqs, dur):
        return np.concatenate([_sweep(f, f, dur, 0.3, "square") for f in freqs])
    return {
        "jump": _to_sound(_sweep(300, 700, 0.15, 0.35)),
        "style": _to_sound(_sweep(900, 1400, 0.10, 0.25)),
        "power": _to_sound(arpeggio((523, 659, 784, 1047), 0.07)),
        "level": _to_sound(arpeggio((392, 523, 659, 784, 1047), 0.09)),
        "shield_break": _to_sound(_noise(0.25, 0.5) * 0.6 + _sweep(600, 150, 0.25, 0.4, "square")),
        "crash": _to_sound(_noise(0.5, 0.45) + _sweep(300, 60, 0.5, 0.4)),
    }


# ------------------------------------------------------------------ jogo ----
class Game:
    def __init__(self):
        self.font = pygame.font.Font(None, 34)
        self.big = pygame.font.Font(None, 68)
        self.sfx = {}
        self.muted = False
        self.music_ch = None
        try:
            self.sounds = [make_track(lv) for lv in LEVELS]
            self.sfx = make_sfx()
        except Exception:  # sem áudio disponível: o jogo roda mudo
            self.sounds = []
            self.sfx = {}
        self.best = self.load_best()
        self.state = "menu"
        self.reset()

    # --- persistência do recorde
    def load_best(self):
        try:
            with open("highscore.txt") as f:
                return int(f.read().strip())
        except Exception:
            return 0

    def save_best(self):
        try:
            with open("highscore.txt", "w") as f:
                f.write(str(self.best))
        except Exception:
            pass

    # --- estado
    def reset(self):
        self.level = 0
        self.level_t = 0.0
        self.t = 0.0
        self.px = LANES[1]
        self.pv = 0.0
        self.lane = 1
        self.jump_t = -1.0
        self.obstacles = []
        self.score = 0.0
        self.scroll = 0.0
        self.beat_t = 0.0
        self.popups = []
        self.banner_t = 3.0
        self.shield = False  # escudo: absorve uma batida
        self.x2_t = 0.0  # segundos restantes de pontos em dobro
        self.safe = 1  # faixa que sempre fica livre (garante que existe caminho)

    def start(self):
        self.reset()
        self.state = "play"
        self.play_music()

    def play_music(self):
        if self.sounds:
            pygame.mixer.stop()
            self.music_ch = self.sounds[self.level].play(loops=-1)
            if self.muted and self.music_ch:
                self.music_ch.set_volume(0.0)

    def game_over(self):
        self.state = "over"
        if self.sounds:  # sem áudio, não há o que parar
            pygame.mixer.stop()
        self.sfx_play("crash")
        if int(self.score) > self.best:
            self.best = int(self.score)
            self.save_best()

    # --- entrada
    def move(self, d):
        self.lane = max(0, min(2, self.lane + d))

    def jump(self):
        if self.jump_t < 0:
            self.jump_t = 0.0
            self.sfx_play("jump")

    def sfx_play(self, name):
        if not self.muted and name in self.sfx:
            self.sfx[name].play()

    def toggle_pause(self):
        if self.state == "play":
            self.state = "pause"
            if self.sounds:
                pygame.mixer.pause()
        elif self.state == "pause":
            self.state = "play"
            if self.sounds:
                pygame.mixer.unpause()

    def auto_pause(self):  # pausa sozinho quando a janela perde o foco
        if self.state == "play":
            self.toggle_pause()

    def toggle_mute(self):
        self.muted = not self.muted
        if self.music_ch:
            self.music_ch.set_volume(0.0 if self.muted else 1.0)

    def key(self, k):
        if k == pygame.K_m:
            self.toggle_mute()
            return
        if k in (pygame.K_p, pygame.K_ESCAPE) and self.state in ("play", "pause"):
            self.toggle_pause()
            return
        if self.state == "pause":
            return
        if self.state != "play":
            if k in (pygame.K_RETURN, pygame.K_SPACE):
                self.start()
            return
        if k in (pygame.K_LEFT, pygame.K_a):
            self.move(-1)
        elif k in (pygame.K_RIGHT, pygame.K_d):
            self.move(1)
        elif k in (pygame.K_UP, pygame.K_w, pygame.K_SPACE):
            self.jump()

    def tap(self, pos):
        if self.state == "pause":
            self.toggle_pause()
        elif self.state != "play":
            self.start()
        elif pos[0] < W / 3:
            self.move(-1)
        elif pos[0] > 2 * W / 3:
            self.move(1)
        else:
            self.jump()

    # --- lógica
    def speed(self):
        return min(300 + self.t * 3, 650)

    def spawn(self):
        lanes = random.sample(range(3), 3)  # faixas em ordem aleatória
        if random.random() <= LEVELS[self.level]["density"]:
            n = 2 if random.random() < min(0.15 + 0.1 * self.level, 0.45) else 1
            # sempre sobra um caminho: a faixa segura muda no máximo uma faixa por linha
            if n == 2:
                safe = random.choice([f for f in range(3) if abs(f - self.safe) <= 1])
                lanes = [f for f in range(3) if f != safe] + [safe]
            elif lanes[0] == self.safe:  # bloqueou a faixa segura: passa para a vizinha livre
                safe = min(lanes[1:], key=lambda f: abs(f - self.safe) + random.random() * 0.1)
            else:
                safe = self.safe
            self.safe = safe
            free = lanes[n:]  # faixas que ficaram livres nesta batida
            for lane in lanes[:n]:
                o = {
                    "lane": lane, "x": LANES[lane], "y": -100.0, "passed": False,
                    "kind": "box" if random.random() < 0.25 else "dancer",
                    "phase": random.random() * 6.28,
                    "col": random.choice(DANCER_COLORS),
                    "swerve_to": None, "swerve_t": 0.0,
                }
                # dançarino de branco: troca para uma faixa vizinha que está livre
                if o["kind"] == "dancer" and random.random() < SWERVE_CHANCE[self.level]:
                    near = [f for f in free if abs(f - lane) == 1 and f != self.safe]
                    if near:
                        o["swerve_to"] = random.choice(near)
                        o["col"] = (255, 255, 255)
                        free.remove(o["swerve_to"])  # reserva a faixa de destino
                self.obstacles.append(o)
            lanes = free
        # power-up raro, sempre numa faixa que ficou livre
        if lanes and random.random() < 0.10:
            self.obstacles.append({
                "lane": lanes[0], "x": LANES[lanes[0]], "y": -100.0, "passed": False,
                "kind": "power", "power": random.choice(("shield", "x2")),
            })

    def collect(self, power):
        self.sfx_play("power")
        if power == "shield":
            self.shield = True
            self.popup("ESCUDO!", self.px, PLAYER_Y - 90)
        else:
            self.x2_t = 8.0
            self.popup("PONTOS x2!", self.px, PLAYER_Y - 90)

    def popup(self, text, x, y):
        self.popups.append([text, x, y, 0.8])

    def update(self, dt):
        if self.state != "play":
            return
        self.t += dt
        self.level_t += dt
        self.banner_t = max(0.0, self.banner_t - dt)
        if self.level_t >= LEVEL_TIME and self.level < len(LEVELS) - 1:
            self.level += 1
            self.level_t = 0.0
            self.beat_t = 0.0
            self.banner_t = 3.0
            self.play_music()
            self.sfx_play("level")

        spd = self.speed()
        mult = 2 if self.x2_t > 0 else 1
        self.x2_t = max(0.0, self.x2_t - dt)
        self.scroll += spd * dt
        self.score += spd * dt / 20 * mult

        # deslize com inércia (mola amortecida): o patinador derrapa um pouco
        acc = (LANES[self.lane] - self.px) * 60 - self.pv * 9
        self.pv += acc * dt
        self.px += self.pv * dt

        if self.jump_t >= 0:
            self.jump_t += dt
            if self.jump_t > 0.65:
                self.jump_t = -1.0

        # obstáculos nascem no ritmo da música
        beat = 60.0 / LEVELS[self.level]["bpm"]
        self.beat_t += dt
        while self.beat_t >= beat:
            self.beat_t -= beat
            self.spawn()

        pr = pygame.Rect(0, 0, 36, 56)
        pr.center = (self.px, PLAYER_Y)
        airborne = self.jump_t >= 0 and 0.12 < self.jump_t < 0.53
        for o in self.obstacles:
            o["y"] += spd * dt
            target = o.get("swerve_to")
            if target is not None and o["y"] > SWERVE_Y:
                o["swerve_t"] += dt
                if o["swerve_t"] > SWERVE_WARN:  # depois do aviso, desliza de lado
                    goal = LANES[target]
                    step = SWERVE_SPEED * dt
                    if abs(goal - o["x"]) <= step:
                        o["x"] = goal
                        o["lane"] = target
                        o["swerve_to"] = None
                    else:
                        o["x"] += step if goal > o["x"] else -step
            ox = o["x"]
            w, h = {"dancer": (54, 80), "box": (64, 36), "power": (44, 44)}[o["kind"]]
            r = pygame.Rect(0, 0, w, h)
            r.center = (ox, o["y"])
            hit = r.colliderect(pr)
            if o["kind"] == "power":
                if hit:
                    self.collect(o["power"])
                    o["dead"] = True
                continue
            if hit and not (o["kind"] == "box" and airborne):
                if self.shield:  # o escudo absorve a batida e some
                    self.shield = False
                    o["dead"] = True
                    self.sfx_play("shield_break")
                    self.popup("ESCUDO QUEBROU!", self.px, PLAYER_Y - 90)
                    continue
                self.game_over()
                return
            if not o["passed"] and o["y"] > PLAYER_Y + 60:
                o["passed"] = True
                if o["kind"] == "dancer" and abs(ox - self.px) < 90:
                    self.score += 5 * mult
                    self.sfx_play("style")
                    self.popup(f"ESTILO! +{5 * mult}", self.px, PLAYER_Y - 70)
                elif o["kind"] == "box" and airborne:
                    self.score += 5 * mult
                    self.sfx_play("style")
                    self.popup(f"PULO! +{5 * mult}", self.px, PLAYER_Y - 70)
        self.obstacles = [o for o in self.obstacles
                          if o["y"] < H + 100 and not o.get("dead")]
        for p in self.popups:
            p[2] -= 40 * dt
            p[3] -= dt
        self.popups = [p for p in self.popups if p[3] > 0]

    # --- desenho
    def draw_floor(self, s, lv):
        s.fill(lv["bg"])
        off = self.scroll % 80
        n = int(self.scroll // 80)
        for row in range(-1, H // 80 + 2):
            for col in range(W // 80 + 1):
                color = lv["tiles"][(row - n + col) % 2]
                pygame.draw.rect(s, color, (col * 80, row * 80 + off, 80, 80))
        if lv.get("stars"):
            for i, (x, y, ph) in enumerate(STARS):
                sy = (y + self.scroll * 0.25) % H  # descem devagar, dando profundidade
                b = int(140 + 115 * math.sin(self.t * 3 + ph))
                pygame.draw.circle(s, (b, b, 255), (int(x), int(sy)), 1 + i % 2)
        if lv.get("snow"):
            for x, y, v, r, ph in SNOW:
                sx = x + 14 * math.sin(self.t * 1.3 + ph)
                pygame.draw.circle(s, (255, 255, 255), (int(sx), int((y + self.t * v) % H)), r)
        if lv.get("confetti"):
            for x, y, v, c, ph in CONFETTI:
                sx = x + 20 * math.sin(self.t * 2 + ph)
                pygame.draw.rect(s, c, (int(sx), int((y + self.t * v) % H), 5, 8))
        for x in (W * 0.35, W * 0.65):
            pygame.draw.line(s, (255, 255, 255), (x, 0), (x, H), 2)

    def draw_lights(self, s, lv):
        beat = 60.0 / lv["bpm"]
        phase = int(self.t / beat) % 2
        for i in range(7):
            c = lv["lights"][(i + phase) % 2]
            y = 22 + 8 * math.sin(self.t * 3 + i)
            pygame.draw.circle(s, c, (int(30 + i * 70), int(y)), 9)
        cx, cy = W // 2, 70
        if lv.get("sun"):  # sol retrô com faixas, no lugar da bola de espelhos
            pygame.draw.circle(s, (255, 190, 90), (cx, cy), 62)
            for k in range(5):
                pygame.draw.rect(s, lv["tiles"][1], (cx - 62, cy + 8 + k * 11, 124, 3 + k))
            return
        pygame.draw.circle(s, (210, 215, 230), (cx, cy), 30)
        for k in range(8):
            a = self.t * 1.5 + k * math.pi / 4
            pygame.draw.line(s, (255, 255, 255), (cx, cy),
                             (cx + 30 * math.cos(a), cy + 30 * math.sin(a)), 1)
        pygame.draw.line(s, (200, 200, 200), (cx, 0), (cx, cy - 30), 2)

    def draw_dancer(self, s, x, y, col, phase):
        sway = math.sin(self.t * 6 + phase) * 6
        arm = math.sin(self.t * 8 + phase)
        pygame.draw.line(s, (30, 30, 60), (x - 6, y + 22), (x - 10 + sway, y + 40), 7)
        pygame.draw.line(s, (30, 30, 60), (x + 6, y + 22), (x + 10 + sway, y + 40), 7)
        pygame.draw.rect(s, col, (x - 14 + sway * 0.3, y - 20, 28, 44), border_radius=8)
        pygame.draw.line(s, col, (x - 14, y - 12), (x - 30, y - 30 + arm * 10), 6)
        pygame.draw.line(s, col, (x + 14, y - 12), (x + 30, y - 30 - arm * 10), 6)
        hx = int(x + sway * 0.5)
        pygame.draw.circle(s, (60, 35, 20), (hx, int(y - 34)), 15)  # cabelo black power
        pygame.draw.circle(s, (240, 200, 160), (hx, int(y - 30)), 11)

    def draw_box(self, s, x, y):
        pygame.draw.rect(s, (25, 25, 30), (x - 32, y - 18, 64, 36), border_radius=5)
        pygame.draw.circle(s, (90, 90, 100), (int(x), int(y)), 12, 3)
        pygame.draw.circle(s, (90, 90, 100), (int(x), int(y)), 4)

    def draw_power(self, s, x, y, kind):
        pulse = 3 * math.sin(self.t * 8)
        color = (90, 220, 255) if kind == "shield" else (255, 215, 0)
        pygame.draw.circle(s, (255, 255, 255), (int(x), int(y)), int(25 + pulse), 2)
        pygame.draw.circle(s, color, (int(x), int(y)), 18)
        img = self.font.render("S" if kind == "shield" else "x2", True, (20, 20, 40))
        s.blit(img, img.get_rect(center=(x, y)))

    def draw_warning(self, s, x, y, target):
        if int(self.t * 10) % 2 == 0:  # pisca
            return
        d = 1 if LANES[target] > x else -1
        pygame.draw.polygon(s, (255, 60, 60),
                            [(x + d * 50, y), (x + d * 30, y - 14), (x + d * 30, y + 14)])
        img = self.big.render("!", True, (255, 60, 60))
        s.blit(img, img.get_rect(center=(x, y - 85)))

    def draw_player(self, s):
        h = 0.0
        if self.jump_t >= 0:
            h = 70 * math.sin(math.pi * self.jump_t / 0.65)
        x, y = self.px, PLAYER_Y - h
        pygame.draw.ellipse(s, (0, 0, 0), (x - 22, PLAYER_Y + 28, 44, 12))
        lean = max(-1, min(1, self.pv / 300)) * 10
        pygame.draw.line(s, (240, 240, 240), (x - 7, y + 20), (x - 9, y + 38), 7)
        pygame.draw.line(s, (240, 240, 240), (x + 7, y + 20), (x + 9, y + 38), 7)
        for wx in (-12, -5, 5, 12):  # rodinhas dos patins
            pygame.draw.circle(s, (255, 60, 60), (int(x + wx), int(y + 42)), 3)
        pygame.draw.rect(s, (255, 215, 0), (x - 14 + lean * 0.4, y - 20, 28, 44), border_radius=8)
        arm = math.sin(self.t * 7)
        pygame.draw.line(s, (255, 215, 0), (x - 14, y - 10), (x - 28, y - 22 + arm * 8), 6)
        pygame.draw.line(s, (255, 215, 0), (x + 14, y - 10), (x + 28, y - 22 - arm * 8), 6)
        hx = int(x + lean)
        pygame.draw.circle(s, (80, 40, 20), (hx, int(y - 34)), 14)
        pygame.draw.circle(s, (230, 185, 145), (hx, int(y - 30)), 11)
        pygame.draw.rect(s, (255, 60, 90), (hx - 12, int(y - 36), 24, 5))  # faixa na testa
        if self.shield:
            pygame.draw.circle(s, (90, 220, 255), (int(x), int(y)), 44, 3)

    def center_text(self, s, text, y, font=None, color=(255, 255, 255)):
        img = (font or self.font).render(text, True, color)
        s.blit(img, img.get_rect(center=(W // 2, y)))

    def draw(self, s):
        lv = LEVELS[self.level]
        self.draw_floor(s, lv)
        self.draw_lights(s, lv)
        for o in sorted(self.obstacles, key=lambda o: o["y"]):
            x = o["x"]
            if o["kind"] == "dancer":
                self.draw_dancer(s, x, o["y"], o["col"], o["phase"])
                if o.get("swerve_to") is not None and o["y"] > SWERVE_Y:
                    self.draw_warning(s, x, o["y"], o["swerve_to"])
            elif o["kind"] == "box":
                self.draw_box(s, x, o["y"])
            else:
                self.draw_power(s, x, o["y"], o["power"])
        self.draw_player(s)
        for text, x, y, _ in self.popups:
            self.center_text(s, text, int(y), color=(255, 255, 120))
        s.blit(self.font.render(f"Pontos: {int(self.score)}", True, (255, 255, 255)), (12, 120))
        s.blit(self.font.render(f"Recorde: {self.best}", True, (255, 255, 255)), (12, 150))
        s.blit(self.font.render(f"Fase {self.level + 1}: {lv['name']}", True, (255, 255, 255)), (12, 180))
        if self.shield:
            s.blit(self.font.render("Escudo ativo", True, (90, 220, 255)), (12, 210))
        if self.x2_t > 0:
            s.blit(self.font.render(f"Pontos x2: {self.x2_t:.0f}s", True, (255, 215, 0)), (12, 240))
        if self.state == "play" and self.banner_t > 0:
            self.center_text(s, f"FASE {self.level + 1}", 330, self.big, (255, 240, 120))
            self.center_text(s, lv["name"], 380)
        if self.state == "menu":
            self.center_text(s, "DISCO ROLLER", 300, self.big, (255, 240, 120))
            self.center_text(s, "Toque ou ENTER para começar", 360)
            self.center_text(s, "Setas: faixa | Espaço: pular", 400)
            self.center_text(s, "P: pausa | M: som", 440)
        elif self.state == "over":
            self.center_text(s, "FIM DE JOGO", 300, self.big, (255, 100, 100))
            self.center_text(s, f"Pontos: {int(self.score)}", 355)
            self.center_text(s, "Toque ou ENTER para tentar de novo", 400)
        elif self.state == "pause":
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((0, 0, 0, 150))
            s.blit(veil, (0, 0))
            self.center_text(s, "PAUSADO", 320, self.big, (255, 240, 120))
            self.center_text(s, "P ou toque para continuar", 380)
        if self.muted:
            s.blit(self.font.render("Som desligado (M)", True, (200, 200, 200)), (12, H - 32))


async def main():
    pygame.mixer.pre_init(SR, -16, 2, 512)
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Disco Roller")
    game = Game()
    clock = pygame.time.Clock()
    while True:
        dt = min(clock.tick(60) / 1000.0, 0.05)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                return
            if e.type == pygame.KEYDOWN:
                game.key(e.key)
            elif e.type == pygame.MOUSEBUTTONDOWN:
                game.tap(e.pos)
            elif e.type == pygame.WINDOWFOCUSLOST:
                game.auto_pause()
        game.update(dt)
        game.draw(screen)
        pygame.display.flip()
        await asyncio.sleep(0)  # necessário para rodar no navegador via Pygbag


if __name__ == "__main__":
    asyncio.run(main())
