"""Controller-driven relative pointer, wheel and click events through uinput."""
import math


def stick_velocity(stick, speed):
    x, y = stick
    length = math.hypot(x, y)
    deadzone = .18
    if length <= deadzone:
        return 0, 0
    scale = speed * ((min(1, length)-deadzone)/(1-deadzone))**2 / length
    return x*scale, y*scale


class Mouse:
    def __init__(self):
        import evdev
        self.e = e = evdev.ecodes
        self.pointer = evdev.UInput({
            e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT],
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL],
        }, name='UWT Virtual Mouse')
        try:
            # Announce a keyboard separately so libinput identifies both roles.
            self.keyboard = evdev.UInput({e.EV_KEY: list(range(1, 59))}, name='UWT Virtual Mouse Keys')
        except BaseException:
            self.pointer.close()
            raise
        self.buttons = {'b': (self.pointer, e.BTN_LEFT), 'y': (self.pointer, e.BTN_RIGHT),
                        'a': (self.keyboard, e.KEY_ESC)}
        self.held = set()
        self.remainder = [0., 0.]
        self.wheel = None
        self.repeat_at = 0.
        self.last_move = None

    def button(self, action, pressed, now):
        if action in self.buttons:
            if pressed == (action in self.held):
                return
            device, code = self.buttons[action]
            if pressed:
                self.held.add(action)
            device.write(self.e.EV_KEY, code, int(pressed))
            device.syn()
            if not pressed:
                self.held.discard(action)
        elif pressed:
            self.scroll(action)
            self.wheel, self.repeat_at = action, now+.35

    def scroll(self, direction):
        self.pointer.write(self.e.EV_REL, self.e.REL_WHEEL, 1 if direction == 'up' else -1)
        self.pointer.syn()

    def update(self, controller, now):
        elapsed = .025 if self.last_move is None else min(.05, now-self.last_move)
        self.last_move = now
        down = controller.logical(navigation=False)
        if 'hotkey' in down:
            self.wheel = None
            return
        if self.wheel not in down:
            self.wheel = None
        elif now >= self.repeat_at:
            self.scroll(self.wheel)
            self.repeat_at = now+.10
        fine = stick_velocity(controller.stick('joystick2'), 360)
        speed = fine if any(fine) else stick_velocity(controller.stick('joystick1'), 1250)
        moved = False
        for index, code in enumerate((self.e.REL_X, self.e.REL_Y)):
            self.remainder[index] += speed[index]*elapsed
            delta = int(self.remainder[index])
            if delta:
                self.remainder[index] -= delta
                self.pointer.write(self.e.EV_REL, code, delta)
                moved = True
        if moved:
            self.pointer.syn()

    def release(self):
        for action in tuple(self.held):
            self.button(action, False, 0)
        self.remainder[:] = [0., 0.]
        self.last_move = None
        self.wheel = None

    def close(self):
        try:
            self.release()
        finally:
            self.keyboard.close()
            self.pointer.close()
