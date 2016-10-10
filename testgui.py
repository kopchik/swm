#!/usr/bin/env python3


from kivy.app import App
from kivy.uix.button import Button


cfg = [
    {"type": "title",
     "title": "Test application"},

    {"type": "options",
     "title": "My first key",
     "desc": "Description of my first key",
     "section": "section1",
     "key": "key1",
     "options": ["value1", "value2", "another value"]},

    {"type": "numeric",
     "title": "My second key",
     "desc": "Description of my second key",
     "section": "section1",
     "key": "key2"}
]


class TestApp(App):

    def build_settings(self, settings):
        settings.add_json_panel('Test application', self.config, data=cfg)


if __name__ == '__main__':
    TestApp().run()
