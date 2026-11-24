from dataclasses import dataclass
from functools import lru_cache
from math import ceil, cos, pi, radians, sin
from pathlib import Path
from random import Random
from time import monotonic

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPolygon, QRegion

from .catalog import BUILDINGS, ROOF_HEIGHT, TREES

SPRITES = Path(__file__).with_name("sprites")
SIZES = {"small": (8, 5), "medium": (11, 7), "large": (14, 9)}
TEST_LENGTH = {"cafe": 6., "phone": 6., "warehouse": 8., "night": 12.,
               "mail": 8., "weather": 12., "shop": 9., "books": 8., "cyber": 8.}
TRAIN_TRAVEL = 3.
BOX_TRIP = 2.8
SHOP_TRAVEL = 2.6


@lru_cache(maxsize=None)
def sprite(name):
    return QImage(str(SPRITES / f"{name}.png"))


@lru_cache(maxsize=72)
def material_sprite(name, walls="", roof=""):
    original = sprite(name)
    if not (walls or roof):
        return original
    result = original.copy()
    for part, color in (("walls", walls), ("roof", roof)):
        if not color:
            continue
        mask = sprite(f"{name}_{part}")
        target = QColor(color)
        pixels = []
        for y in range(mask.height()):
            for x in range(mask.width()):
                if mask.pixelColor(x, y).alpha():
                    source = original.pixelColor(x, y)
                    value = .2126 * source.red() + .7152 * source.green() + .0722 * source.blue()
                    pixels.append((x, y, value, source.alpha()))
        if pixels:
            center = sum(pixel[2] for pixel in pixels) / len(pixels)
            for x, y, value, alpha in pixels:
                factor = value / max(1, center)
                gleam = max(0., (value - center) * .18)
                channels = [min(255, round(component * factor + gleam))
                            for component in (target.red(), target.green(), target.blue())]
                result.setPixelColor(x, y, QColor(*channels, alpha))
    return result


@dataclass(frozen=True)
class Tile:
    u: int
    v: int
    art: str


@dataclass(frozen=True)
class Prop:
    u: float
    v: float
    art: str
    light: float = 0.0


class Layout:
    def __init__(self, seed, size, trees=TREES):
        self.seed, self.size = seed, size
        self.wide, self.deep = SIZES[size]
        rng = Random(seed)
        self.x0 = (self.deep + 1) * 24
        self.height = 71 + (self.wide + self.deep) * 12 + 18
        self.width = (self.wide + self.deep + 2) * 24
        self.main_street = rng.randrange(1, 3)
        rows = {self.main_street, self.deep - 2}
        rows.update(range(self.main_street + 3, self.deep - 3, 3))
        columns = set(range(rng.randrange(2, 4), self.wide - 1, 3))
        self.tiles = []
        self.props = []
        self.tree_lots = []

        station = (rng.randrange(2, self.wide - 2), self.deep - 2)
        storefronts = [
            (u, v)
            for v in range(1, self.deep - 2)
            for u in range(1, self.wide - 1)
            if v not in rows and u not in columns
        ]
        freight_lots = [p for p in storefronts if p[1] == self.main_street + 1]
        freight = rng.choice(freight_lots or storefronts)
        storefronts.remove(freight)
        # The bar sits on a street so its façade has space for the interactive overlay.
        cafes = [p for p in storefronts if p[1] + 1 in rows or p[0] + 1 in columns]
        cafe = rng.choice(cafes or storefronts)
        storefronts.remove(cafe)
        phone = rng.choice(storefronts)
        self.landmarks = {"cafe": cafe, "phone": phone, "warehouse": freight, "station": station}
        locations = [(u, v) for v in range(self.deep - 2) for u in range(self.wide)
                     if u not in columns and v not in rows and (u, v) not in self.landmarks.values()]
        placement = Random(seed ^ 0x6A4B9)
        placement.shuffle(locations)
        locations.sort(key=lambda p: p[1] + 1 not in rows and p[0] + 1 not in columns)
        additions = dict(zip(locations, (key for key in BUILDINGS if key != "cafe")))
        self.landmarks.update({key: lot for lot, key in additions.items()})
        landmarks = {p: name for name, p in self.landmarks.items()}
        for v in range(self.deep):
            for u in range(self.wide):
                name = landmarks.get((u, v))
                if v == self.deep - 1:
                    kind = "rail"
                elif name and (u, v) not in additions:
                    kind = "stone"
                    self.props.append(Prop(u, v, name, .27 if name == "cafe" else .68))
                elif v in rows or u in columns:
                    kind = "road"
                    if (u + v) % 3 == 0 or rng.random() < .15:
                        self.props.append(Prop(u - .25, v + .20, "lamp"))
                    elif v == self.deep - 2 and abs(u - station[0]) > 1:
                        self.props.append(Prop(u, v + .12, "bench"))
                    elif rng.random() < .25:
                        self.props.append(Prop(u + .24, v - .20, "shrubs"))
                else:
                    kind = rng.choice(("grass", "stone", "stone"))
                    value = rng.random()
                    if value < .24:
                        rng.randrange(3)  # Preserve the layout RNG sequence used by existing seeds.
                        self.tree_lots.append((u, v))
                    elif value < .87:
                        self.props.append(Prop(u, v, f"house{rng.randrange(3)}", rng.uniform(.29, .94)))
                    else:
                        self.props += [Prop(u - .17, v - .07, "shrubs"), Prop(u + .22, v + .16, "crate")]
                self.tiles.append(Tile(u, v, f"{kind}{rng.randrange(4)}"))
        for u in range(1, self.wide, 3):
            self.props.append(Prop(u + .34, self.deep - .49, "lamp"))
            self.props.append(Prop(u + .73, self.deep - .41, "shrubs"))
        self.tree_lots = [lot for lot in self.tree_lots if lot not in additions]
        self.fixed_props = [p for p in self.props if (int(p.u + .5), int(p.v + .5)) not in additions]
        self.fixed_props.extend(Prop(*lot, art, .6) for lot, art in additions.items())
        self.set_trees(trees)

    def set_trees(self, enabled):
        allowed = set(enabled) & TREES.keys()
        plants = Random(self.seed ^ 0x728B1)
        self.props = self.fixed_props.copy()
        if allowed:
            for u, v in self.tree_lots:
                priority = plants.sample(list(TREES), len(TREES))
                species = next(key for key in priority if key in allowed)
                self.props.append(Prop(u, v, TREES[species][1]))
        self.props.sort(key=lambda p: (p.u + p.v, p.u))

    def point(self, u, v):
        return QPoint(round(self.x0 + (u - v) * 24), round(71 + (u + v) * 12))

    def shore(self, u):
        return self.point(u, self.deep - .51) + QPoint(2, 10)

    @property
    def roof(self):
        return self.roof_at("cafe")

    def roof_at(self, key):
        return self.point(*self.landmarks[key]) + QPoint(1, -ROOF_HEIGHT[key])

def ease(t):
    t = min(1., max(0., t))
    return t*t*(3 - 2*t)


@dataclass
class StationDelivery:
    arrival: float
    loading_start: float
    loading_end: float
    departure: float

    @classmethod
    def start(cls, now, boxes):
        loading = now + TRAIN_TRAVEL + .25
        end = loading + BOX_TRIP * boxes
        return cls(now, loading, end, end + .45)

    def add(self, now, boxes):
        if now >= self.loading_end:
            self.loading_start = now
            self.loading_end = now
        self.loading_end += BOX_TRIP * boxes
        if now < self.departure:
            self.departure = self.loading_end + .45

    def active(self, now):
        return now < max(self.loading_end, self.departure + TRAIN_TRAVEL)


@dataclass
class ShopDelivery:
    arrival: float
    departure: float | None = None

    @property
    def loading_start(self):
        return self.arrival + SHOP_TRAVEL

    def finish_loading(self, now):
        trips = ceil(max(0., now - self.loading_start) / BOX_TRIP)
        self.departure = self.loading_start + trips * BOX_TRIP

    def active(self, now):
        return self.departure is None or now < self.departure + SHOP_TRAVEL


class Scenes:
    def __init__(self):
        self.enabled = {}
        self.levels = {}
        self.events = {}
        self.tests = {}
        self.delivery = None
        self.shop_delivery = None
        self.lighting_changed = monotonic()
        self.night = False
        self.night_from = 0.0
        self.music = False
        self.external = set()
        self.wind = None
        self.colors = {}
        self.clip_until = 0.
        self.neon_target = False
        self.neon_from = 0.
        self.neon_changed = monotonic()

    def configure(self, activities):
        self.enabled = {key: entry["enabled"] for key, entry in activities.items()}
        for key, enabled in self.enabled.items():
            if not enabled:
                self.levels.pop(key, None)
                self.tests.pop(key, None)
                self.events.pop(key, None)
        self.refresh_night()
        if not self.enabled.get("station"):
            self.delivery = None
        if not self.enabled.get("shop"):
            self.shop_delivery = None
        if not self.enabled.get("night"):
            self.night_from = 0.
        if not self.enabled.get("cyber"):
            self.neon_target = False
            self.neon_from = 0.

    def refresh_night(self):
        now = monotonic()
        sleeping = self.active("night", now)
        if sleeping != self.night:
            self.night_from = self.dim(now)
            self.lighting_changed = now
            self.night = sleeping
            if sleeping:
                self.events["night"] = now

    def dim(self, now):
        elapsed = ease((now - self.lighting_changed) / 4)
        return self.night_from + (float(self.night) - self.night_from) * elapsed

    def active(self, key, now):
        return self.enabled.get(key, False) and (
            key in self.levels or key in self.external or now < self.tests.get(key, 0)
        )

    def refresh_neon(self, now):
        target = self.active("cyber", now)
        if target != self.neon_target:
            self.neon_from = self.neon(now)
            self.neon_target = target
            self.neon_changed = now

    def neon(self, now):
        t = ease((now - self.neon_changed) / 1.25)
        return self.neon_from + (float(self.neon_target) - self.neon_from) * t

    def test(self, key):
        if self.enabled.get(key):
            now = monotonic()
            if key == "station":
                self.deliver(now, 1)
                return
            self.tests[key] = now + TEST_LENGTH[key]
            if key in ("warehouse", "night"):
                self.events[key] = now
            self.refresh_night()

    def deliver(self, now, boxes):
        if self.delivery is not None and self.delivery.active(now):
            self.delivery.add(now, boxes)
        else:
            self.delivery = StationDelivery.start(now, boxes)

    def refresh_shop(self, now):
        requested = self.active("shop", now)
        delivery = self.shop_delivery
        if delivery is not None and not delivery.active(now):
            self.shop_delivery = delivery = None
        if delivery is None:
            if requested:
                self.shop_delivery = ShopDelivery(now)
        elif requested and delivery.departure is not None and now <= delivery.departure:
            delivery.departure = None
        elif not requested and delivery.departure is None:
            delivery.finish_loading(now)

    def update_triggers(self, levels, events):
        now = monotonic()
        for key in ("warehouse", "station"):
            if not self.enabled.get(key):
                continue
            new_bindings = levels.get(key, set()) - self.levels.get(key, set())
            count = events.get(key, int(bool(new_bindings)))
            if count and key == "station":
                self.deliver(now, count)
            elif count:
                self.events[key] = now
        # Discrete bindings can also trigger continuous scenes for a short visit.
        for key in events.keys() - {"warehouse", "station"}:
            self.test(key)
        self.levels = {key: rules for key, rules in levels.items() if self.enabled.get(key)}
        self.refresh_night()

    def interval(self, now):
        if (0 <= now - self.events.get("warehouse", -100) < TEST_LENGTH["warehouse"]
                or self.delivery is not None and self.delivery.active(now)
                or self.shop_delivery is not None
                or self.active("weather", now) or now - self.neon_changed < 1.25):
            return 33
        if self.night and now - self.events.get("night", -100) < 10:
            return 75
        return 200 if self.night else 90


def paint_building_effects(painter, name, origin, scenes, now):
    if name == "mail" and scenes.active(name, now):
        painter.drawImage(origin, sprite("mail_flag"))
    elif name == "books" and scenes.enabled.get(name) and (scenes.active(name, now) or now < scenes.clip_until):
        painter.drawImage(origin, sprite("books_note"))
    elif name == "cyber":
        painter.setOpacity(scenes.neon(now))
        painter.drawImage(origin, sprite("cyber_neon"))
        painter.setOpacity(1.)
    elif name == "weather" and scenes.enabled.get(name):
        wind = scenes.wind
        if now < scenes.tests.get(name, 0):
            wind = now * 130 % 360
        if wind is not None:
            angle = radians(wind)
            x, y = round(8 * (sin(angle) + cos(angle))), round(4 * (sin(angle) - cos(angle)))
            hub = origin + QPoint(37, 17)
            painter.setPen(QColor("#a5cacc"))
            painter.drawLine(hub - QPoint(x, y), hub + QPoint(x, y))
            painter.fillRect(hub.x() + x - 1, hub.y() + y - 1, 3, 3, QColor("#f1b074"))


class Renderer:
    def __init__(self, layout):
        self.layout = layout
        self.size = QSize(layout.width, layout.height)
        self.ground = QImage(self.size, QImage.Format.Format_ARGB32_Premultiplied)
        self.ground.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.ground)
        self.paint_shore(painter)
        for tile in sorted(layout.tiles, key=lambda t: (t.u + t.v, t.u)):
            painter.drawImage(layout.point(tile.u, tile.v) - QPoint(24, 12), sprite(tile.art))
        for u in range(1, layout.wide, 2):
            origin = layout.shore(u + .13) + QPoint(-7, 3)
            painter.drawImage(origin - QPoint(36, 66), sprite(f"shoal{u % 3}"))
        painter.end()

    def paint_shore(self, painter):
        layout = self.layout
        rng = Random(layout.seed ^ 0x508F)
        samples = []
        for i in range(layout.wide * 5 + 1):
            u = i / 5 - .50
            taper = min(1., i / 11, (layout.wide * 5 - i) / 11)
            width = (39 + 9 * sin(u * 1.4) + 4 * sin(u * 3.2) + rng.randrange(-3, 4)) * taper
            samples.append((layout.shore(u), width))

        def outline(inset):
            outer = []
            for p, width in samples:
                distance = max(0, width - inset)
                outer.append(p + QPoint(-round(distance), round(distance * .51)))
            return QPolygon([p + QPoint(3, -4) for p, _ in samples] + outer[::-1])

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for inset, color in ((0, QColor(24, 48, 65, 67)), (2, QColor(18, 43, 59, 143)),
                             (5, QColor(15, 43, 59, 231))):
            painter.setBrush(color)
            painter.drawPolygon(outline(inset))
        painter.setClipRegion(QRegion(outline(5)))
        painter.setOpacity(.19)
        for u in range(layout.wide + 1):
            origin = layout.shore(u) - QPoint(26, 1)
            painter.drawImage(origin, sprite(f"water{rng.randrange(4)}"))
            painter.drawImage(origin + QPoint(-23, 12), sprite(f"water{rng.randrange(4)}"))
        painter.setOpacity(1)
        for p, width in samples:
            for _ in range(rng.randrange(1, 5)):
                shift = rng.uniform(3, width) if width > 3 else width
                x, y = p.x() - round(shift) + rng.randrange(-3, 4), p.y() + round(shift * .51)
                color = rng.choice(("#214555", "#183648", "#294f60", "#183b4b"))
                painter.fillRect(x, y, rng.randrange(1, 7), 1, QColor(color))
        painter.restore()

    def paint(self, painter, scenes, now, bouncing_at=None, scale=1.0, bouncing_key="cafe"):
        layout = self.layout
        painter.drawImage(0, 0, self.ground)
        dim = scenes.dim(now)
        cafe = scenes.active("cafe", now) or scenes.music
        phone = scenes.active("phone", now)
        pulse = (now - bouncing_at) / .22 if bouncing_at is not None else 2.
        hop = round(3.7 * sin(pi * pulse) / scale) if 0 <= pulse < 1 else 0
        if scenes.night:
            dim = min(1.0, dim)
        if scenes.active("weather", now):
            for i in range(1, layout.wide, 2):
                pos = layout.point(i + .28, layout.main_street + .12)
                painter.fillRect(pos.x() - 5, pos.y(), 10, 3, QColor(71, 125, 160, 150))
                painter.fillRect(pos.x() - 2, pos.y() + (int(now * 6) + i) % 3, 5, 1, QColor("#8aa0af"))
        actors = self.actors(scenes, now)
        props = sorted((*layout.props, *actors), key=lambda p: (p.u + p.v, p.u)) if actors else layout.props
        for prop in props:
            point = layout.point(prop.u, prop.v)
            origin = point - QPoint(36, 66)
            if prop.art == bouncing_key:
                origin -= QPoint(0, hop)
            palette = scenes.colors.get(prop.art, {})
            painter.drawImage(origin, material_sprite(prop.art, palette.get("walls", ""), palette.get("roof", "")))
            offset = (round(prop.u * 23 + prop.v * 17) % 11) / 50
            light = prop.light * (1 - .90 * ease((dim - offset) / .8))
            if prop.art == "cafe":
                light = max(light * 1.9, .98 if cafe else 0, .95 * (1 - abs(pulse - .65)) if pulse < 1.15 else 0)
            if light > 0:
                painter.setOpacity(light)
                painter.drawImage(origin, sprite(prop.art + "_lit"))
                painter.setOpacity(1)
            if prop.art == "phone" and phone and (now * 2.5) % 1 < .47:
                painter.drawImage(origin, sprite("phone_beacon"))
            if prop.art == "cafe" and scenes.music:
                self.notes(painter, origin, now)
            if prop.art == "warehouse" and not scenes.night:
                self.smoke(painter, origin + QPoint(30, 25), now)
            if prop.art in BUILDINGS:
                paint_building_effects(painter, prop.art, origin, scenes, now)
        self.water_lights(painter, now, dim)

    @staticmethod
    def smoke(painter, origin, now):
        for index in range(4):
            phase = (now * .30 + index * .19) % 1
            x = origin.x() - 2 - round(phase * 12)
            y = origin.y() - 9 - round(phase * 15)
            radius = 2 + round(phase * 4)
            color = QColor(179, 109, 117, round(87 * (1 - phase)))
            painter.fillRect(x - 1, y, radius + 2, 2, color)
            painter.fillRect(x, y - 2, radius, 5, color)

    @staticmethod
    def notes(painter, origin, now):
        phase = now % 3.5
        if phase > 1.65:
            return
        x = origin.x() + 50 + round(phase * 6)
        y = origin.y() + 35 - round(phase * 9)
        color = QColor(255, 189, 113, round(255 * (1 - phase / 1.65)))
        painter.fillRect(x - 2, y + 4, 3, 2, color)
        painter.fillRect(x, y, 1, 5, color)
        painter.fillRect(x + 1, y, 2, 1, color)

    def water_lights(self, painter, now, dim):
        phase = int(now * 4)
        for u in range(2, self.layout.wide - 1, 3):
            p = self.layout.shore(u + .25) + QPoint(-15, 7)
            for n in range(3):
                color = QColor(193, 110 + n*12, 83, round((68 + n*15) * (1 - .7 * dim)))
                painter.fillRect(p.x() - n + (phase + n) % 3, p.y() + n*2, 2 + (phase + u + n) % 5, 1, color)

    def actors(self, scenes, now):
        layout = self.layout
        result = []
        step = int(now * 9) % 2 == 0
        worker = "worker_step" if step else "worker"
        elapsed = now - scenes.events.get("warehouse", -100)
        if 0 <= elapsed < 8:
            u, v = layout.landmarks["warehouse"]
            distance = ease(elapsed / 2.4) * u
            if elapsed > 6:
                distance += ease((elapsed - 6) / 2) * (layout.wide - u)
            road = layout.main_street + .15
            entrance = v - .58
            if v <= layout.main_street:
                entrance = v + .58
            lane = road + (entrance - road) * ease((elapsed - 1.8) / .6) * (1 - ease((elapsed - 6) / 1.1))
            result.append(Prop(distance - .1, lane, "van"))
            if 2.5 < elapsed < 5.9:
                t = ease((elapsed - 2.5) / 3.4)
                x, y = u + .33 - .24*t, entrance + (v - entrance) * t
                result.extend((Prop(x, y + .04 * sin(elapsed * 25), worker), Prop(x + .15, y, "crate")))
        delivery = scenes.delivery
        if delivery is not None and delivery.active(now):
            station, _ = layout.landmarks["station"]
            track = layout.deep - 1
            arrival = ease((now - delivery.arrival) / TRAIN_TRAVEL)
            departure = ease((now - delivery.departure) / TRAIN_TRAVEL)
            u = (station + 1) * arrival - 1 + (layout.wide - station + 1) * departure
            for offset, art in ((0., "engine"), (-.91, "train")):
                if -.25 <= u + offset < layout.wide:
                    result.append(Prop(u + offset, track, art))
            if delivery.loading_start <= now < delivery.loading_end:
                phase = ((now - delivery.loading_start) % BOX_TRIP) / BOX_TRIP
                carrying = phase < .58
                t = ease(phase / .58 if carrying else (1 - phase) / .42)
                x, y = station - .25 + .67*t, track - .30 - .66*t
                result.append(Prop(x, y, worker))
                if carrying:
                    result.append(Prop(x + .13, y, "crate"))
        elapsed = now - scenes.events.get("night", -100)
        if scenes.night and 3 < elapsed < 10:
            result.append(Prop(.4 + (layout.wide - 1) * (elapsed - 3) / 7,
                               layout.main_street + .26 + .038 * sin(elapsed * 24), "cat_step" if step else "cat"))
        if scenes.active("weather", now):
            for delay in (0., 4.4):
                phase = (now + delay) % 9. / 9.
                result.append(Prop(.5 + phase * (layout.wide - 1.), layout.main_street + .20,
                                   "umbrella" if step else "umbrella_step"))
        shop = scenes.shop_delivery
        if shop is not None and shop.active(now):
            u, v = layout.landmarks["shop"]
            path = 1. - ease((now - shop.arrival) / SHOP_TRAVEL)
            if shop.departure is not None:
                path += ease((now - shop.departure) / SHOP_TRAVEL)
            result.append(Prop(u + min(1.4, layout.wide - u - .4) * path, v + .72, "van"))
            if now >= shop.loading_start and (shop.departure is None or now < shop.departure):
                phase = ((now - shop.loading_start) % BOX_TRIP) / BOX_TRIP
                carrying = phase < .58
                t = ease(phase / .58 if carrying else (1 - phase) / .42)
                y = v + .74 - .71 * t
                result.append(Prop(u + .26, y, worker))
                if carrying:
                    result.append(Prop(u + .39, y, "crate"))
        return result
