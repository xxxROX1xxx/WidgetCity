from functools import lru_cache
from math import ceil, floor
from time import monotonic

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QBitmap, QCursor, QFont, QFontMetrics, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from .cards import ActivityContent
from .catalog import BUILDINGS
from .city import ease, sprite
from .media import MediaState, source_label
from .shell import KEY_COLOR, ShellLayer, is_window, logical_rect
from .steam import open_steam
from .windows import escape_pressed

FLOATING = (Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus)


def fit_position(point, size, bounds, margin=9):
    return QPoint(
        min(max(point.x(), bounds.left() + margin), max(bounds.left() + margin, bounds.right() + 1 - size.width() - margin)),
        min(max(point.y(), bounds.top() + margin), max(bounds.top() + margin, bounds.bottom() + 1 - size.height() - margin)),
    )


class Surface(QWidget):
    def __init__(self):
        super().__init__(None, FLOATING)
        self.hwnd = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def surface_handle(self):
        if self.hwnd and not is_window(self.hwnd):
            self.hide()
            self.destroy()
        self.hwnd = int(self.winId())
        return self.hwnd

    def display(self, shell, rect, **style):
        shell.place(self, rect, **style)
        if not self.isVisible():
            self.show()
            shell.place(self, rect, **style)


@lru_cache(maxsize=None)
def sprite_runs(name):
    art = sprite(name)
    runs = []
    for y in range(art.height()):
        run = None
        for x in range(art.width() + 1):
            solid = x < art.width() and art.pixelColor(x, y).alpha() >= 128
            if solid and run is None:
                run = x
            if not solid and run is not None:
                runs.append((run, x, y))
                run = None
    return tuple(runs)


@lru_cache(maxsize=160)
def sprite_region(name, scale):
    region = QRegion()
    for start, end, y in sprite_runs(name):
        left, right = floor(start * scale), ceil(end * scale)
        top, bottom = floor(y * scale), ceil((y + 1) * scale)
        region |= QRegion(left, top, right - left, bottom - top)
    return region


class BuildingTarget(Surface):
    pressed = Signal(str)

    def __init__(self, key):
        super().__init__()
        self.key = key
        self.setAccessibleName(BUILDINGS[key])
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def place(self, desktop):
        layout = desktop.view.renderer.layout
        scale = desktop.scale
        u, v = layout.landmarks[self.key]
        point = layout.point(u, v)
        origin = point - QPoint(36, 66)
        base = desktop.rect.topLeft() + QPoint(floor(origin.x() * scale), floor(origin.y() * scale))
        art = sprite(self.key)
        bounds = QRect(base, QSize(ceil(art.width() * scale), ceil(art.height() * scale)))
        region = QRegion(sprite_region(self.key, scale))
        for prop in layout.props:
            if (prop.u + prop.v, prop.u) <= (u + v, u):
                continue
            delta = layout.point(prop.u, prop.v) - point
            if abs(delta.x()) >= art.width() or delta.y() >= art.height():
                continue
            relative = QPoint(floor((origin.x() + delta.x()) * scale) - floor(origin.x() * scale),
                              floor((origin.y() + delta.y()) * scale) - floor(origin.y() * scale))
            region -= sprite_region(prop.art, scale).translated(relative)
        screen = QApplication.screenAt(bounds.center()) or QApplication.primaryScreen()
        for native_rect in desktop.icon_rectangles:
            icon = logical_rect(native_rect, screen)
            if bounds.intersects(icon):
                region -= QRegion(icon.translated(-base))
        if region.isEmpty():
            self.hide()
            return
        self.setMask(region)
        self.display(desktop.shell, bounds, interactive=True, opacity=1)

    def paintEvent(self, _event):
        painter = QPainter(self)
        # The window has 1/255 opacity. Its mask follows the resting sprite, excluding icons.
        painter.fillRect(self.rect(), QColor("#513349"))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(self.key)
            event.accept()


class Player(Surface):
    command = Signal(int, str)
    SIZE = QSize(304, 115)

    def __init__(self):
        super().__init__()
        self.setFixedSize(self.SIZE)
        self.setWindowTitle("Музыкальный плеер")
        self.state = MediaState()
        self.cover = QPixmap()
        self.buttons = []
        for index, (icon, name, action) in enumerate((
            ("⏮", "Предыдущий трек", "previous"),
            ("▶", "Воспроизвести", "toggle"),
            ("⏭", "Следующий трек", "next"),
        )):
            button = QPushButton(icon, self)
            button.setFixedSize(33, 26)
            button.move(88 + index * 39, 77)
            button.setObjectName("transport")
            button.setFlat(False)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.clicked.connect(lambda checked=False, action=action: self.send(action))
            self.buttons.append(button)
        self.apply(self.state)

    def send(self, action):
        self.command.emit(self.state.route, self.state.toggle if action == "toggle" else action)

    def apply(self, state):
        if state.cover != self.state.cover:
            self.cover = QPixmap()
            if state.cover:
                self.cover.loadFromData(state.cover)
        self.state = state
        previous, toggle, next_button = self.buttons
        previous.setEnabled(state.previous)
        toggle.setEnabled(bool(state.toggle))
        next_button.setEnabled(state.next)
        toggle.setText("Ⅱ" if state.playing else "▶")
        label = "Пауза" if state.playing else "Воспроизвести"
        toggle.setToolTip(label)
        toggle.setAccessibleName(label)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), KEY_COLOR)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#533746"))
        painter.setBrush(QColor("#211a29"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 13, 13)
        painter.setPen(QColor("#b16e55"))
        painter.drawLine(16, 1, 84, 1)
        cover_box = QRect(12, 13, 64, 64)
        if not self.cover.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            cover = self.cover.scaled(cover_box.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            source = QRect((cover.width() - 64)//2, (cover.height() - 64)//2, 64, 64)
            painter.drawPixmap(cover_box, cover, source)
        else:
            painter.fillRect(cover_box, QColor("#342638"))
            for i, width in enumerate((8, 13, 20, 13, 8)):
                painter.fillRect(24 + 8*i, 45 - width//2, 4, width, QColor("#d99068") if i == 2 else QColor("#795065"))
            painter.fillRect(16, 17, 2, 2, QColor("#976274"))
            painter.fillRect(68, 69, 2, 2, QColor("#976274"))
        source = source_label(self.state.source) if self.state.source else "Медиасессия Windows"
        self.text(painter, 88, 14, source, 9, "#dfa781")
        self.text(painter, 88, 30, self.state.title or self.state.status or "Без названия", 14, "#f3dfd6", True)
        subtitle = self.state.artist or ("Выберите источник в настройках" if self.state.status else "—")
        self.text(painter, 88, 51, subtitle, 10, "#b8a3b5")

    @staticmethod
    def text(painter, x, y, value, size, color, bold=False):
        font = QFont("Segoe UI")
        font.setPixelSize(size)
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(QColor(color))
        metrics = QFontMetrics(font)
        painter.drawText(x, y + metrics.ascent(), metrics.elidedText(value, Qt.TextElideMode.ElideRight, 204))


class ActivityCard(Surface):
    SIZE = QSize(350, 260)

    def __init__(self, key, services):
        super().__init__()
        self.setWindowTitle(BUILDINGS[key])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 12, 13, 12)
        layout.addWidget(ActivityContent(key, services))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), KEY_COLOR)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#674557"))
        painter.setBrush(QColor("#211a29"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 13, 13)


class DesktopCity:
    def __init__(self, renderer, scenes, position, scale, services):
        self.view = CityView(renderer, scenes, self)
        self.services = services
        self.targets = {key: BuildingTarget(key) for key in BUILDINGS}
        for target in self.targets.values():
            target.pressed.connect(self.click_building)
        self.player = Player()
        self.cards = {"cafe": self.player}
        self.card_key = None
        self.player_allowed = True
        self.card_open = False
        self.moving = False
        self.card_level = 0.
        self.transition = None
        self.bounce = None
        self.bounce_key = "cafe"
        self.position = position
        self.percent = scale
        self.scale = 1.
        self.visible = False
        self.rect = QRect()
        self.shell = ShellLayer()
        self.icon_rectangles = []
        self.shell_timer = QTimer(self.view, interval=1700)
        self.shell_timer.timeout.connect(self.refresh_shell)
        self.timer = QTimer(self.view, interval=16, timerType=Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick_player)
        self.steam_timer = QTimer(self.view, interval=150, singleShot=True)
        self.steam_timer.timeout.connect(open_steam)
        self.open_changed = lambda _opened: None
        self.place()

    def set_layout(self, renderer):
        self.view.renderer = renderer
        self.bounce = None
        self.place()
        self.view.update()

    def set_scale(self, percent):
        self.percent = percent
        self.place()
        self.view.update()

    def place(self):
        screen = None
        if self.position is not None:
            screen = QApplication.screenAt(QPoint(*self.position))
        screen = screen or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        natural = self.view.renderer.size
        self.scale = min(self.percent / 100, (bounds.width() - 18) / natural.width(), (bounds.height() - 18) / natural.height())
        size = QSize(ceil(natural.width() * self.scale), ceil(natural.height() * self.scale))
        if self.position is None:
            point = QPoint(bounds.right() - size.width() + 1 - 14, bounds.bottom() - size.height() + 1 - 13)
        else:
            point = QPoint(*self.position)
        self.rect = QRect(fit_position(point, size, bounds), size)
        if self.visible:
            self.place_view()
            self.sync_target()

    def refresh_shell(self):
        shell = self.shell if self.shell.valid() else ShellLayer.discover()
        icon_rectangles = shell.icon_rects()
        changed = self.shell != shell
        icons_changed = self.icon_rectangles != icon_rectangles
        self.shell, self.icon_rectangles = shell, icon_rectangles
        if changed:
            self.place()
            self.view.update()
        elif icons_changed:
            self.sync_target()

    def place_view(self):
        self.view.display(self.shell, self.rect, interactive=self.moving,
                          opacity=220 if self.moving else 255, passthrough=not self.moving)

    def sync_target(self):
        should_show = self.visible and self.shell.interactive and not self.moving
        if should_show:
            layout = self.view.renderer.layout
            for key in sorted(self.targets, key=lambda name: (sum(layout.landmarks[name]), layout.landmarks[name][0])):
                target = self.targets[key]
                if key == "cafe" and not self.player_allowed:
                    target.hide()
                else:
                    target.place(self)
            if self.card_key and self.cards[self.card_key].isVisible():
                self.place_card()
        else:
            self.hide_targets()
            if not self.shell.interactive and self.card_key:
                self.close_card(immediate=True)

    def hide_targets(self):
        for target in self.targets.values():
            target.hide()

    def show(self, visible):
        self.visible = visible
        if visible:
            self.refresh_shell()
            self.place()
            self.view.update()
            self.shell_timer.start()
        else:
            self.shell_timer.stop()
            self.close_card(immediate=True)
            self.hide_targets()
            self.view.hide()

    def allow_player(self, enabled):
        self.player_allowed = enabled
        if not enabled and self.card_key == "cafe":
            self.close_card(immediate=True)
        if self.visible:
            self.refresh_shell()
            self.sync_target()

    def move_mode(self, enabled):
        self.moving = enabled
        self.close_card(immediate=True)
        self.hide_targets()
        self.view.drag = None
        self.view.setCursor(Qt.CursorShape.SizeAllCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.place()
        self.view.update()

    def move_to(self, global_point):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.screenAt(global_point)
        if screen:
            global_point = fit_position(global_point, self.rect.size(), screen.availableGeometry(), 0)
        self.rect.moveTopLeft(global_point)
        self.place_view()

    def place_card(self):
        card = self.cards[self.card_key]
        p = self.view.renderer.layout.roof_at(self.card_key)
        anchor = self.rect.topLeft() + QPoint(round(p.x() * self.scale), round(p.y() * self.scale))
        screen = QApplication.screenAt(anchor) or self.view.screen()
        bounds = screen.availableGeometry()
        size = card.SIZE.boundedTo(bounds.size() - QSize(18, 18))
        y = anchor.y() - size.height() - 10
        if y < bounds.top() + 9:
            y = anchor.y() + 48
        point = QPoint(anchor.x() - size.width() // 2, y + round(8 * (1 - self.card_level)))
        rect = QRect(fit_position(point, size, bounds), size)
        card.display(self.shell, rect, interactive=True, opacity=round(self.card_level * 255))

    def click_building(self, key):
        now = monotonic()
        if key == "cyber":
            self.close_card(immediate=True)
            self.steam_timer.start()
        elif self.card_open and self.card_key == key:
            self.close_card()
        else:
            if self.card_key != key:
                self.close_card(immediate=True)
                if key not in self.cards:
                    self.cards[key] = ActivityCard(key, self.services)
                self.card_key = key
            self.card_open = True
            if key == "cafe":
                self.open_changed(True)
            self.transition = (now + .115, self.card_level, 1.)
        self.bounce, self.bounce_key = now, key
        self.timer.start()
        self.view.update()

    def close_card(self, immediate=False):
        if self.card_open and self.card_key == "cafe":
            self.open_changed(False)
        self.card_open = False
        if immediate:
            self.transition = None
            self.card_level = 0.
            self.bounce = None
            if self.card_key:
                self.cards[self.card_key].hide()
            self.card_key = None
            self.timer.stop()
        elif self.card_key:
            self.transition = (monotonic(), self.card_level, 0.)
            self.timer.start()

    def tick_player(self):
        now = monotonic()
        if self.card_open and escape_pressed():
            self.close_card()
        if self.transition is not None:
            start, origin, goal = self.transition
            if now >= start:
                self.card_level = origin + (goal - origin) * ease((now - start) / .20)
                if self.card_level > 0.01 and self.card_key:
                    previously_visible = self.cards[self.card_key].isVisible()
                    self.place_card()
                    if not previously_visible and self.card_key == "mail":
                        self.services.mark_mail_seen()
                elif self.card_key:
                    self.cards[self.card_key].hide()
                if now - start >= .20:
                    self.transition = None
                    if not self.card_open:
                        self.card_key = None
        if self.bounce is not None:
            self.view.update()
            if now - self.bounce >= .25:
                self.bounce = None
        if self.transition is None and self.bounce is None:
            if self.card_open:
                if self.timer.interval() != 40:
                    self.timer.setInterval(40)
            else:
                self.timer.stop()
                self.timer.setInterval(16)
        elif self.timer.interval() != 16:
            self.timer.setInterval(16)


class CityView(Surface):
    position_changed = Signal(object)

    def __init__(self, renderer, scenes, desktop):
        super().__init__()
        self.setWindowTitle("WidgetCity · Город")
        self.renderer, self.scenes, self.desktop = renderer, scenes, desktop
        self.drag = None

    def paintEvent(self, _event):
        # Explorer's desktop supports color-key layered children. Dither sprite alpha
        # into the mask so shore pixels and glows blend into the wallpaper at pixel scale.
        frame = QImage(self.renderer.size, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(Qt.GlobalColor.transparent)
        canvas = QPainter(frame)
        self.renderer.paint(canvas, self.scenes, monotonic(), self.desktop.bounce,
                            self.desktop.scale, self.desktop.bounce_key)
        canvas.end()
        image = QPixmap.fromImage(frame.convertToFormat(QImage.Format.Format_RGB32))
        image.setMask(QBitmap.fromImage(frame.createAlphaMask(Qt.ImageConversionFlag.OrderedAlphaDither)))
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#231d2c") if self.desktop.moving else KEY_COLOR)
        p.save()
        p.scale(self.desktop.scale, self.desktop.scale)
        p.drawPixmap(0, 0, image)
        p.restore()
        if self.desktop.moving:
            p.setPen(QColor("#c58e6e"))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event):
        if self.desktop.moving and event.button() == Qt.MouseButton.LeftButton:
            self.drag = event.globalPosition().toPoint() - self.desktop.rect.topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag is not None:
            self.desktop.move_to(event.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, event):
        if self.drag is not None and event.button() == Qt.MouseButton.LeftButton:
            self.drag = None
            self.desktop.position = [self.desktop.rect.x(), self.desktop.rect.y()]
            self.position_changed.emit(self.desktop.position)
