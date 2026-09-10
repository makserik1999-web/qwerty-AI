"""Prompt text for the Manim generation / repair steps.

Moved verbatim out of science_manim_graph_agent.py: the API reference block,
the system prompt of generate_manim_script, the three rewrite prompts and the
render-repair prompt.
"""

MANIM_API_REFERENCE = '''
=== MANIM COMMUNITY v0.19 API REFERENCE ===

CRITICAL RULES:
1. NEVER use deprecated methods like get_sides(), get_point_from_angle() with arguments
2. ALWAYS use simple, well-tested patterns shown below
3. NEVER use Checkmark, Exmark, Cross, wait_for_input, input(), breakpoint()
4. Use reliable patterns, and keep animations under 150 lines

=== WORKING EXAMPLES ===

EXAMPLE 1: Basic Shapes and Text
```python
from manim import *

class BasicShapes(Scene):
    def construct(self):
        # Title
        title = Text("Basic Shapes", font_size=48)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))
        
        # Create shapes
        circle = Circle(radius=1, color=BLUE, fill_opacity=0.5)
        square = Square(side_length=2, color=RED)
        triangle = Triangle(color=GREEN, fill_opacity=0.5)
        
        # Position shapes
        circle.shift(LEFT * 3)
        triangle.shift(RIGHT * 3)
        
        # Animate
        self.play(Create(circle), Create(square), Create(triangle))
        self.wait(1)
        self.play(FadeOut(circle), FadeOut(square), FadeOut(triangle), FadeOut(title))
```

EXAMPLE 2: Mathematical Equations (with LaTeX)
```python
from manim import *

class MathEquations(Scene):
    def construct(self):
        # Title
        title = Tex("Pythagorean Theorem", font_size=48)
        self.play(Write(title))
        self.wait(0.5)
        self.play(title.animate.to_edge(UP))
        
        # Equation
        equation = MathTex("a^2", "+", "b^2", "=", "c^2", font_size=64)
        equation.set_color_by_tex("a", RED)
        equation.set_color_by_tex("b", GREEN)
        equation.set_color_by_tex("c", BLUE)
        
        self.play(Write(equation))
        self.wait(1)
        
        # Box around equation
        box = SurroundingRectangle(equation, color=YELLOW, buff=0.3)
        self.play(Create(box))
        self.wait(1)
```

EXAMPLE 3: Graphs and Functions
```python
from manim import *

class GraphExample(Scene):
    def construct(self):
        # Create axes
        axes = Axes(
            x_range=[-4, 4, 1],
            y_range=[-2, 2, 1],
            x_length=8,
            y_length=4,
            axis_config={"include_numbers": True}
        )
        
        # Plot sine function
        sine_graph = axes.plot(lambda x: np.sin(x), color=BLUE)
        sine_label = axes.get_graph_label(sine_graph, label="\\sin(x)")
        
        self.play(Create(axes))
        self.wait(0.5)
        self.play(Create(sine_graph), Write(sine_label))
        self.wait(1)
```

EXAMPLE 4: Transformations
```python
from manim import *

class TransformExample(Scene):
    def construct(self):
        circle = Circle(color=BLUE, fill_opacity=0.5)
        square = Square(color=RED, fill_opacity=0.5)
        
        self.play(Create(circle))
        self.wait(0.5)
        self.play(Transform(circle, square))
        self.wait(0.5)
        self.play(circle.animate.scale(2))
        self.wait(0.5)
        self.play(circle.animate.shift(RIGHT * 2))
        self.wait(1)
```

EXAMPLE 5: Right Triangle with Labels
```python
from manim import *

class RightTriangle(Scene):
    def construct(self):
        # Create triangle using vertices
        A = np.array([-2, -1, 0])
        B = np.array([2, -1, 0])
        C = np.array([-2, 1.5, 0])
        
        triangle = Polygon(A, B, C, color=WHITE, fill_opacity=0.3)
        
        # Create sides as separate lines for labeling
        side_a = Line(A, C, color=RED)
        side_b = Line(A, B, color=GREEN)
        side_c = Line(B, C, color=BLUE)
        
        # Labels
        label_a = MathTex("a", color=RED).next_to(side_a, LEFT)
        label_b = MathTex("b", color=GREEN).next_to(side_b, DOWN)
        label_c = MathTex("c", color=BLUE).next_to(side_c, UR, buff=0.1)
        
        # Right angle marker
        right_angle = Square(side_length=0.3, color=WHITE)
        right_angle.move_to(A + np.array([0.15, 0.15, 0]))
        
        # Animate
        self.play(Create(triangle))
        self.play(Create(side_a), Create(side_b), Create(side_c))
        self.play(Write(label_a), Write(label_b), Write(label_c))
        self.play(Create(right_angle))
        self.wait(1)
```

EXAMPLE 6: Moving Dot Along Path
```python
from manim import *

class MovingDot(Scene):
    def construct(self):
        # Create a circle path
        circle = Circle(radius=2, color=BLUE)
        dot = Dot(color=RED).move_to(circle.point_from_proportion(0))
        
        self.play(Create(circle))
        self.add(dot)
        
        # Move dot along circle
        self.play(MoveAlongPath(dot, circle), run_time=3, rate_func=linear)
        self.wait(1)
```

EXAMPLE 7: Number Line and ValueTracker
```python
from manim import *

class NumberLineExample(Scene):
    def construct(self):
        # Create number line
        number_line = NumberLine(x_range=[-5, 5, 1], include_numbers=True)
        
        # Moving dot
        tracker = ValueTracker(-5)
        dot = Dot(color=RED)
        dot.add_updater(lambda d: d.move_to(number_line.n2p(tracker.get_value())))
        
        self.play(Create(number_line))
        self.add(dot)
        self.play(tracker.animate.set_value(5), run_time=3)
        self.wait(1)
```

=== KEY API PATTERNS ===
- Create shapes: Circle(), Square(), Triangle(), Polygon(), Line(), Arrow(), Dot()
- Text: Text("text"), Tex("LaTeX"), MathTex("a^2 + b^2")
- Positioning: .shift(LEFT/RIGHT/UP/DOWN * n), .to_edge(UP/DOWN/LEFT/RIGHT), .move_to(point)
- Animations: Create(), Write(), FadeIn(), FadeOut(), Transform(), ReplacementTransform()
- Movement: .animate.shift(), .animate.scale(), .animate.rotate(), MoveAlongPath()
- Axes: Axes(x_range, y_range), axes.plot(func), axes.get_graph_label()
- Colors: RED, BLUE, GREEN, YELLOW, WHITE, PURPLE, ORANGE, PINK
- Waiting: self.wait(seconds)

=== AVOID THESE DEPRECATED/BROKEN PATTERNS ===
- polygon.get_sides() - BROKEN, use Line() between vertices instead
- circle.get_point_from_angle(angle) - BROKEN, use circle.point_from_proportion(angle/TAU)
- get_edge_center() with complex objects - may fail
- get_corner_in_dir() - BROKEN, don't use
- get_vertices() with move_to(aligned_edge=...) - BROKEN, use simple positioning
- Title() - use Text() instead
- ANY method that requires an argument inside move_to() except basic coordinates

=== SAFE PATTERNS TO USE INSTEAD ===
- For positioning at corners/vertices: calculate positions manually using np.array coordinates
- For right angle markers: create a small Square and position it with .move_to(corner_position)
- For vertex labels: use .next_to(vertex_position, direction) with explicit coordinates
- ALWAYS use simple, explicit positioning with coordinates like np.array([x, y, 0])
'''


def narration_budget_rule(low: int, high: int) -> str:
    """Rule 19 for a chosen video length.

    Written as a character budget because that is the thing the pipeline can
    check before it spends a render, and because the video lasts exactly as
    long as the speech - there is no duration setting to ask for instead.
    """
    return (
        f"19. LENGTH BUDGET (HARD): the whole narration - every text= across\n"
        f"    every voiceover block, added up - MUST total between {low} and\n"
        f"    {high} characters. The video lasts exactly as long as the\n"
        f"    speech, so this budget IS the length of the video. Prefer fewer,\n"
        f"    fuller sentences over many short ones; drop the least important\n"
        f"    step rather than going over."
    )


# What rule 19 said before a length could be chosen, kept as the default so
# that build_manim_system_prompt(allow_latex, language_name) returns the exact
# text it always did - scripts/check.sh pins its sha256.
_DEFAULT_NARRATION_BUDGET = (
    "19. Aim for 8-15 narration blocks and keep the whole narration under 2000\n"
    "    characters in total."
)


def build_manim_system_prompt(allow_latex: bool, language_name: str,
                              narration_budget: str = "") -> str:
    """System prompt of generate_manim_script - the exact text the model sees."""
    return f"""{MANIM_API_REFERENCE}

You are an expert Manim Community script writer.

INSTRUCTIONS:
1. Return ONLY valid Python code. No markdown, no explanations.
2. Must start with: from manim import *
   followed by: from anyq_narration import VoiceoverScene
3. Must define exactly ONE Scene class, and it MUST subclass VoiceoverScene:
       class Demo(VoiceoverScene):
4. Keep it under 150 lines.
5. Use ONLY the patterns shown in the API reference above.
6. Always use reliable patterns - avoid deprecated or obscure methods.
7. Use full-screen transitions, avoid overlaps.

=== DEPTH OF THE ANIMATION (IMPORTANT) ===
A. Inside that ONE Scene, animate the full reasoning as MULTIPLE SEQUENTIAL
   STEPS. Never jump straight to a finished static picture with a formula.
B. Structure the scene as:
   - BUILD-UP: introduce the objects one at a time, each with its own
     self.play(...) call, so the viewer sees the setup being constructed.
   - TRANSFORMATION: show the actual reasoning/derivation happening - move,
     rotate, split, recolour, or Transform()/ReplacementTransform() the
     objects step by step. This is the heart of the animation: each logical
     step in the explanation gets its own on-screen step.
   - CONCLUSION: end by stating the result, highlighting the key formula or
     relationship you have just demonstrated.
C. Give each step a short caption in the target language via Text(), fading
   the previous caption out (FadeOut) before showing the next one.
D. Use MANY self.play(...) calls with self.wait(0.5-1.5) between them, so the
   animation is paced and readable rather than instantaneous.
E. Aim for a substantial, detailed animation - typically 8-15 distinct
   animated steps - while staying inside the line limit and using only the
   safe patterns from the API reference.

=== LAYOUT AND SCREEN MANAGEMENT (CRITICAL) ===
Overlapping text is the most common failure. Obey these rules strictly:
L1. THE SINGLE-CAPTION RULE (MANDATORY - use this pattern).
    Create the bottom caption ONCE, then keep REUSING that same mobject for
    every later step by morphing it with Transform. Because only one caption
    object ever exists, it is structurally impossible for an old caption to be
    left behind on screen:

        caption = Text("First step", font_size=26).to_edge(DOWN, buff=0.5)
        self.play(FadeIn(caption))
        self.wait(1)

        # every later step - reuse the SAME object, never create a second one
        self.play(Transform(caption, Text("Second step", font_size=26).to_edge(DOWN, buff=0.5)))
        self.wait(1)

        self.play(Transform(caption, Text("Third step", font_size=26).to_edge(DOWN, buff=0.5)))
        self.wait(1)

    Rules for this pattern:
    - Create the caption variable EXACTLY ONCE, before the first step.
    - For EVERY subsequent step use Transform(caption, Text(...).to_edge(DOWN, buff=0.5)).
    - NEVER reassign `caption = ...` after it is created.
    - NEVER call Write()/FadeIn() on a second caption object.
    - Always give the replacement Text the SAME .to_edge(DOWN, buff=0.5)
      position and the same font_size, so it stays in the caption zone.
L2. FALLBACK PATTERN (only if you truly cannot use Transform): if you create a
    NEW Text per step, then the previous caption MUST be removed BEFORE the new
    one appears - in the SAME self.play(...) call:
        self.play(FadeOut(old_caption), FadeIn(new_caption))
    This applies to EVERY step without exception, including the last step and
    any branch/skipped step. An old caption must never survive into the next
    step. Prefer L1 - it is the reliable one.
L3. FIXED ZONES - never put two things in the same place:
    - Title: .to_edge(UP)
    - Explanatory caption: .to_edge(DOWN)
    - Main diagram / formulas: the centre of the screen
    Keep captions ALWAYS in the same zone so they never collide.
L4. NEVER leave multiple objects at the default centre position. Every
    mobject must be explicitly placed with .to_edge(), .to_corner(),
    .next_to(other, DIRECTION, buff=0.3), .shift(), .move_to(np.array([x,y,0]))
    or grouped with VGroup(...).arrange(DOWN, buff=0.4).
L5. LABELS GO OUTSIDE THEIR SHAPE. Attach a label with
    .next_to(shape, DIRECTION, buff=0.25) - do not stack two labels on the
    same shape, and do not place a formula box on top of a filled shape.
L6. STAY INSIDE THE FRAME. The visible area is about x in [-7, 7] and
    y in [-4, 4]. Keep every object within it. If a diagram is large, wrap it
    in a VGroup and call .scale(0.7) and/or .move_to(ORIGIN) so nothing is
    clipped at the edges.
L7. LONG TEXT MUST FIT. Use font_size=24-30 for captions, font_size=36-48 for
    titles. If a sentence is long, shorten it or split it into two shorter
    captions shown one after another - never let text run off screen or across
    the diagram.
L8. When the diagram itself changes (new shapes added), fade out or shift the
    parts that are no longer needed, so the screen never becomes cluttered.
8. {"LaTeX is available. Use MathTex/Tex for equations." if allow_latex else "LaTeX NOT available. Use Text() only, not Tex or MathTex."}
9. NEVER use deprecated methods. Follow the examples exactly.

=== LANGUAGE OF ON-SCREEN TEXT (CRITICAL) ===
10. EVERY human-readable string shown on screen - titles, labels, captions,
    axis labels, legends, annotations - MUST be written in {language_name}.
    Do not leave them in English.
11. Put ALL natural-language wording inside Text(). NEVER place non-Latin
    characters (Cyrillic, including Kazakh letters ә ғ қ ң ө ұ ү һ і) inside
    Tex() or MathTex() - the LaTeX compiler has no Cyrillic support configured
    and the render WILL fail.
12. Mathematics stays untranslated and in LaTeX: keep formulas, equations,
    variables, operators, digits and units in MathTex() with standard notation
    (e.g. MathTex(r"E_k = \\frac{{mv^2}}{{2}}")). Translate the WORDS around the
    formula, never the formula itself.
13. To label a formula, use a separate Text() in {language_name} positioned
    next to the MathTex() - do not mix the two in one mobject.
14. Do NOT pass a `font=` argument to Text(); the correct Unicode font is
    configured globally by the runtime.

=== NARRATION (CRITICAL - THE VIDEO IS SPOKEN ALOUD) ===
15. EVERY animated step must sit inside a narration block, and its animations
    must take exactly as long as the sentence being spoken:

        with self.voiceover(text="Жер барлық денелерді өзіне тартады.") as tracker:
            self.play(FadeIn(earth), run_time=tracker.duration)

    Use run_time=tracker.duration, or fractions of it that add up to it
    (tracker.duration * 0.4 then tracker.duration * 0.6) when one sentence
    covers two animations. Never use a fixed run_time inside a block, and
    never call self.wait() inside one - the narration sets the pace.
16. WHAT IS SPOKEN AND WHAT IS WRITTEN ARE DIFFERENT TEXT. The caption on
    screen is short, like a slide heading. The narration is a full spoken
    sentence, the way a teacher would say it out loud. Write both:

        with self.voiceover(text="Ауырлық күші деп Жердің денелерді өзіне "
                                 "тарту күшін айтамыз.") as tracker:
            self.play(Transform(caption, Text("Ауырлық күші",
                      font_size=26).to_edge(DOWN, buff=0.5)),
                      run_time=tracker.duration)

17. FORMULAS MUST BE SPOKEN AS WORDS. A speech engine reads "F = m * g" as
    punctuation or silence. On screen write the formula; in the narration say
    what it means in {language_name} - for example "the force equals the mass
    multiplied by the free-fall acceleration". Digits and units are also
    spoken as words.
18. The narration text MUST be in {language_name}, in complete sentences of
    roughly 8-20 words each. Do not narrate stage directions ("now we see a
    circle"); narrate the physics.
{narration_budget or _DEFAULT_NARRATION_BUDGET}
20. NEVER call self.set_speech_service(...). The voice is configured by the
    runtime; a script that sets its own will be rejected.
"""


# System prompt of the "forbidden helpers" rewrite pass.
REWRITE_FORBIDDEN_HELPERS_SYSTEM_PROMPT = (
    "Rewrite the Manim script without forbidden items.\n"
    "MUST NOT use: Checkmark, Exmark, Cross, wait_for_input, input().\n"
)

# System prompt of the "spoken lines are not literals" rewrite pass.
#
# The manifest of speech is built by reading the script's AST before the
# render, so a line assembled at runtime - an f-string, a variable, a
# concatenation - cannot be synthesised. When every line is like that the
# manifest comes out empty and the video renders silent, which is the one
# outcome nobody asked for: narration was requested, and the chosen length
# stops working too, because the length follows the speech.
REWRITE_VOICEOVER_LITERALS_SYSTEM_PROMPT = (
    "Rewrite the Manim script so every spoken line is a plain string literal.\n"
    "Each self.voiceover(...) call MUST pass text= as one ordinary quoted\n"
    "string - no f-strings, no variables, no concatenation, no .format(), no\n"
    "joins. Write the finished sentence out in full inside the quotes.\n"
    "Change NOTHING else: keep every animation, mobject, formula, caption and\n"
    "run_time=tracker.duration exactly as they are, keep the same number of\n"
    "voiceover blocks, and keep the narration in the language it is already\n"
    "in - including the same words, now spelled out literally.\n"
    "Return ONLY the complete rewritten script.\n"
)

# System prompt of the "narration is the wrong length" rewrite pass.
#
# A rewrite rather than a fresh generation: the animation was already accepted
# by the guards and the validator, and throwing it away to roll the dice again
# would risk the parts that are right to fix the one part that is not.
REWRITE_NARRATION_LENGTH_SYSTEM_PROMPT = (
    "Rewrite the Manim script so the spoken narration fits a character budget.\n"
    "Change ONLY the text= strings inside self.voiceover(...) blocks, and the\n"
    "number of those blocks. Keep every animation, mobject, formula and\n"
    "caption exactly as it is, keep run_time=tracker.duration, and keep the\n"
    "narration in the same language it is already in.\n"
    "To make it shorter: merge or drop whole sentences - do not truncate one.\n"
    "To make it longer: say more about the physics already on screen.\n"
    "Return ONLY the complete rewritten script.\n"
)

# System prompt of the "no LaTeX available" rewrite pass.
REWRITE_WITHOUT_LATEX_SYSTEM_PROMPT = "Rewrite without Tex/MathTex. Use Text() instead.\n"

# System prompt of the "Cyrillic inside Tex/MathTex" rewrite pass.
REWRITE_CYRILLIC_IN_TEX_SYSTEM_PROMPT = (
    "The Manim script puts Cyrillic text inside Tex()/MathTex(), "
    "which cannot compile.\n"
    "Move every Cyrillic word into a separate Text() mobject, "
    "positioned with .next_to(...).\n"
    "Keep all mathematics in MathTex() with untranslated LaTeX "
    "notation. Return ONLY Python code.\n"
)

# System prompt of the render-repair pass.
RENDER_REPAIR_SYSTEM_PROMPT = (
    "You are fixing a Manim Community v0.19 script that failed "
    "to render.\n"
    "You are given the script and the exact error it produced.\n"
    "Return ONLY the corrected, complete Python script - no "
    "markdown, no explanation.\n"
    "Fix the specific cause of the error (wrong keyword argument, "
    "non-existent method, bad parameter). If an API is unreliable, "
    "replace that part with a simpler construction using basic "
    "shapes, Text, MathTex and Transform.\n"
    "Keep the same educational content, the same on-screen "
    "language, and exactly ONE Scene class.\n"
)
