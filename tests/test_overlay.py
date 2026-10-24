from __future__ import annotations

from PIL import Image

from autogram.overlay import SlideText, plan_slide, typeset


def test_single_image_gets_headline_and_all_points():
    s = plan_slide("How RAG works", ["retrieve", "augment", "generate"], 0, 1)
    assert s.title == "How RAG works"
    assert s.body == ["retrieve", "augment", "generate"]


def test_carousel_one_point_per_slide():
    pts = ["retrieve", "augment", "generate"]
    slides = [plan_slide("How RAG works", pts, i, 4) for i in range(4)]
    assert slides[0].title == "How RAG works" and "Swipe" in slides[0].footer
    assert [s.title for s in slides[1:]] == pts
    assert slides[3].footer == "4/4"


def test_last_slide_recaps_when_points_would_be_lost():
    pts = ["a", "b", "c", "d"]
    last = plan_slide("H", pts, 2, 3)
    assert last.title == "Recap" and last.body == pts


def test_typeset_keeps_size_and_draws_text():
    bg = Image.new("RGB", (1080, 1350), (40, 60, 90))
    out = typeset(bg, SlideText(title="Attention is a weighted lookup", body=["one", "two"]))
    assert out.size == bg.size
    assert out.getbbox() is not None
    assert list(out.getdata()) != list(bg.getdata())
