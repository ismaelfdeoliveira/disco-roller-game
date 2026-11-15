"""Disco Roller Runner: endless runner numa pista de roller disco dos anos 70.

Controles:
  Teclado: setas ou A/D trocam de faixa, ESPAÇO/seta pra cima/W pula, ENTER inicia.
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
]
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
    buf = buf / max(1e-9, np.max(np.abs(buf))) * 0.85
    pcm = (buf * 32767).astype(np.int16)
    stereo = np.ascontiguousarray(np.column_stack((pcm, pcm)))
    return pygame.sndarray.make_sound(stereo)


# ------------------------------------------------------------------ jogo ----
class Game:
    def __init__(self):
        self.font = pygame.font.Font(None, 34)
        self.big = pygame.font.Font(None, 68)
        try:
            self.sounds = [make_track(lv) for lv in LEVELS]
        except Exception:  # sem áudio disponível: o jogo roda mudo
            self.sounds = []
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

    def start(self):
        self.reset()
        self.state = "play"
        self.play_music()

    def play_music(self):
        if self.sounds:
            pygame.mixer.stop()
            self.sounds[self.level].play(loops=-1)

    def game_over(self):
        self.state = "over"
        pygame.mixer.stop()
        if int(self.score) > self.best:
            self.best = int(self.score)
            self.save_best()

    # --- entrada
    def move(self, d):
        self.lane = max(0, min(2, self.lane + d))

    def jump(self):
        if self.jump_t < 0:
            self.jump_t = 0.0

    def key(self, k):
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
        if self.state != "play":
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
        if random.random() > LEVELS[self.level]["density"]:
            return
        n = 2 if random.random() < 0.15 + 0.1 * self.level else 1
        for lane in random.sample(range(3), n):
            self.obstacles.append({
                "lane": lane, "y": -100.0, "passed": False,
                "kind": "box" if random.random() < 0.25 else "dancer",
                "phase": random.random() * 6.28,
                "col": random.choice(DANCER_COLORS),
            })

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

        spd = self.speed()
        self.scroll += spd * dt
        self.score += spd * dt / 20

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
            ox = LANES[o["lane"]]
            w, h = (54, 80) if o["kind"] == "dancer" else (64, 36)
            r = pygame.Rect(0, 0, w, h)
            r.center = (ox, o["y"])
            if r.colliderect(pr) and not (o["kind"] == "box" and airborne):
                self.game_over()
                return
            if not o["passed"] and o["y"] > PLAYER_Y + 60:
                o["passed"] = True
                if o["kind"] == "dancer" and abs(ox - self.px) < 90:
                    self.score += 5
                    self.popup("ESTILO! +5", self.px, PLAYER_Y - 70)
                elif o["kind"] == "box" and airborne:
                    self.score += 5
                    self.popup("PULO! +5", self.px, PLAYER_Y - 70)
        self.obstacles = [o for o in self.obstacles if o["y"] < H + 100]
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

    def center_text(self, s, text, y, font=None, color=(255, 255, 255)):
        img = (font or self.font).render(text, True, color)
        s.blit(img, img.get_rect(center=(W // 2, y)))

    def draw(self, s):
        lv = LEVELS[self.level]
        self.draw_floor(s, lv)
        self.draw_lights(s, lv)
        for o in sorted(self.obstacles, key=lambda o: o["y"]):
            x = LANES[o["lane"]]
            if o["kind"] == "dancer":
                self.draw_dancer(s, x, o["y"], o["col"], o["phase"])
            else:
                self.draw_box(s, x, o["y"])
        self.draw_player(s)
        for text, x, y, _ in self.popups:
            self.center_text(s, text, int(y), color=(255, 255, 120))
        s.blit(self.font.render(f"Pontos: {int(self.score)}", True, (255, 255, 255)), (12, 120))
        s.blit(self.font.render(f"Recorde: {self.best}", True, (255, 255, 255)), (12, 150))
        s.blit(self.font.render(f"Fase {self.level + 1}: {lv['name']}", True, (255, 255, 255)), (12, 180))
        if self.state == "play" and self.banner_t > 0:
            self.center_text(s, f"FASE {self.level + 1}", 330, self.big, (255, 240, 120))
            self.center_text(s, lv["name"], 380)
        if self.state == "menu":
            self.center_text(s, "DISCO ROLLER", 300, self.big, (255, 240, 120))
            self.center_text(s, "Toque ou ENTER para começar", 360)
            self.center_text(s, "Setas: faixa | Espaço: pular", 400)
        elif self.state == "over":
            self.center_text(s, "FIM DE JOGO", 300, self.big, (255, 100, 100))
            self.center_text(s, f"Pontos: {int(self.score)}", 355)
            self.center_text(s, "Toque ou ENTER para tentar de novo", 400)


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
        game.update(dt)
        game.draw(screen)
        pygame.display.flip()
        await asyncio.sleep(0)  # necessário para rodar no navegador via Pygbag


if __name__ == "__main__":
    asyncio.run(main())
