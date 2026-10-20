"""Curated animation: what gravity is (grades 7-9).

Not one word on screen is written here. Every string comes from S, which
seed_library.py replaces with the dictionary for the language being rendered,
so the same animation serves Kazakh, Russian and English.

That is the whole point of the layout: the animation is reviewed once, and
each extra language costs only a read-through of its strings file. Putting a
literal in this file would quietly ship it to all three languages at once.

Positions are absolute rather than chained with next_to. The three languages
produce captions of very different lengths, and a chain that fits Kazakh
pushes the Russian text off the frame; fixed bands plus _fit() keep every
language inside the same picture.
"""

from manim import *

S = {}  # anyq:strings


class GravityBasics(Scene):
    # Frame is 14.2 x 8. Leave a margin so no language touches the edge.
    MAX_WIDTH = 12.4

    def _fit(self, mobject):
        """Shrink text that a longer translation would push off the frame."""
        if mobject.width > self.MAX_WIDTH:
            mobject.scale(self.MAX_WIDTH / mobject.width)
        return mobject

    def _caption(self, wording, y, size=30, color=WHITE):
        # Takes the wording, not the key: keeping every S["..."] visible at the
        # call site is what lets the content check find missing translations.
        text = Text(wording, font_size=size, color=color)
        self._fit(text)
        text.move_to([0, y, 0])
        return text

    def construct(self):
        title = Text(S["title"], font_size=54, weight=BOLD)
        self._fit(title)
        self.play(Write(title), run_time=1.5)
        self.wait(0.8)
        self.play(title.animate.scale(0.6).move_to([0, 3.4, 0]), run_time=1.0)

        # --- 1. Something falls, because something pulls it -----------------
        # A big circle centred below the frame: only the top cap shows, which
        # reads as ground rather than as a ball.
        earth = Circle(radius=2.4, color=BLUE_D, fill_opacity=0.9)
        earth.move_to([0, -4.9, 0])
        earth_label = Text(S["earth"], font_size=26).move_to([0, -3.1, 0])

        apple = Dot(radius=0.15, color=RED).move_to([0, 1.3, 0])
        pull = Arrow(start=[0, 1.0, 0], end=[0, 0.0, 0], buff=0,
                     color=YELLOW, stroke_width=6)
        pull_label = Text(S["force"], font_size=26, color=YELLOW)
        pull_label.next_to(pull, RIGHT, buff=0.3)

        step1 = self._caption(S["step1"], 2.3)

        self.play(FadeIn(earth, shift=UP * 0.3), FadeIn(earth_label), run_time=1.0)
        self.play(FadeIn(apple, scale=0.5), run_time=0.6)
        self.play(GrowArrow(pull), Write(pull_label), run_time=1.0)
        self.play(Write(step1), run_time=1.4)
        self.wait(0.5)
        self.play(
            apple.animate.move_to([0, -2.35, 0]),
            FadeOut(pull), FadeOut(pull_label),
            run_time=1.2,
        )
        self.wait(1.2)

        # --- 2. The pull goes both ways ------------------------------------
        self.play(
            FadeOut(step1), FadeOut(apple), FadeOut(earth_label), FadeOut(earth),
            run_time=0.8,
        )

        step2 = self._caption(S["step2"], 2.3)
        big = Circle(radius=1.0, color=BLUE_D, fill_opacity=0.9).move_to([-3.2, -0.4, 0])
        small = Circle(radius=0.55, color=GREEN_D, fill_opacity=0.9).move_to([3.2, -0.4, 0])
        arrow_r = Arrow(start=[-1.7, -0.4, 0], end=[-0.5, -0.4, 0], buff=0,
                        color=YELLOW, stroke_width=6)
        arrow_l = Arrow(start=[1.7, -0.4, 0], end=[0.5, -0.4, 0], buff=0,
                        color=YELLOW, stroke_width=6)

        self.play(Write(step2), run_time=1.4)
        self.play(FadeIn(big), FadeIn(small), run_time=0.9)
        self.play(GrowArrow(arrow_r), GrowArrow(arrow_l), run_time=1.0)
        self.wait(1.2)

        # --- 3. Mass and distance decide how strong it is -------------------
        # The formula sits in its own band above the spheres, and the caption
        # in its own band below them: nothing shares a row with the drawing.
        formula = Text(S["formula"], font_size=44, color=YELLOW)
        self._fit(formula)
        formula.move_to([0, 1.2, 0])
        self.play(Write(formula), run_time=1.6)
        self.wait(0.8)

        step3 = self._caption(S["step3"], -2.7, size=28)
        self.play(Write(step3), run_time=1.6)
        self.wait(0.6)

        # Pull them apart: the arrows shrink, because distance weakens the pull.
        self.play(
            big.animate.move_to([-5.4, -0.4, 0]),
            small.animate.move_to([5.4, -0.4, 0]),
            arrow_r.animate.scale(0.4),
            arrow_l.animate.scale(0.4),
            run_time=1.8,
        )
        self.wait(1.6)

        # --- 4. Closing line ------------------------------------------------
        self.play(
            FadeOut(big), FadeOut(small), FadeOut(arrow_r), FadeOut(arrow_l),
            FadeOut(step2), FadeOut(step3), FadeOut(formula),
            run_time=0.9,
        )
        closing = self._caption(S["closing"], 0.0, size=38)
        self.play(Write(closing), run_time=1.8)
        self.wait(2.0)
