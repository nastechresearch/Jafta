"""L'esclusione dal gesto «indietro» della mascotte flottante sta sulla maniglia.

Parcheggiata, Jafta sporge dal bordo destro per poco meno di metà quadrato:
quel che resta visibile sta nella fascia in cui Android legge uno swipe come
*back*. L'esclusione era sulla finestra di lei, e non valeva niente:
``DisplayContent.calculateSystemGestureExclusion`` (AOSP, ``android14-release``)
scorre le finestre dall'alto e a ognuna conta l'esclusione solo dentro l'area
toccabile che quelle sopra non coprono ancora (``touchableRegion.op(unhandled,
INTERSECT)``). La maniglia le sta sopra (aggiunta dopo), toccabile e grande
uguale: alla finestra di lei non restava area.
"""

from __future__ import annotations

from support.kotlin_source import function_body, read_code


def _code() -> str:
    return read_code("FloatingOverlayController")


def test_the_grip_excludes_the_back_gesture() -> None:
    grip = function_body(_code(), "buildGrip")
    assert "systemGestureExclusionRects" in grip
    assert "addOnLayoutChangeListener" in grip
    # In arena (schermo intero) non si esclude: coprirebbe tutto il bordo.
    assert "WindowManager.LayoutParams.MATCH_PARENT" in grip
    assert "emptyList()" in grip


def test_her_window_no_longer_carries_a_useless_exclusion() -> None:
    assert "systemGestureExclusionRects" not in function_body(_code(), "buildMascotWindow")


def test_the_grip_is_the_window_on_top() -> None:
    """Il presupposto dell'argomento: la maniglia è aggiunta per ultima."""
    attach = function_body(_code(), "attach")
    assert attach.index("wm.addView(box, blp)") < attach.index("wm.addView(handle, glp)")
