"""The persona must obey the user's tone instruction — that is the whole contract.

Observed on a real device (2026-10-06): the user wrote "be professional" and
the answer was "professional? boring … you're stuck with me". The shipped
``SOUL.md`` described the personality as one unbending costume — "I'm not a
corporate drone" — with no rule that an explicit request outranks it, so the
identity won over the person who owns the phone.

These tests are behavioural contracts on the *text* of the persona template, not
snapshots of it: they assert the relationships that must hold (the instruction
rule exists, the joke has edges, the work register exists), and they fail if a
rewrite drops one of them. A test that asserted "the file contains exactly this
paragraph" would be a change-detector and would tax every future edit; these
would instead let the wording move.
"""

from pathlib import Path

import pytest

from jafta.utils.android_assets import _RETIRED_TEMPLATE_DIGESTS, template_digest

TEMPLATE = Path("jafta/templates/SOUL.md")


@pytest.fixture(scope="module")
def soul() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _has(soul: str, *needles: str) -> bool:
    """Every phrase present, case- and whitespace-insensitive."""
    haystack = soul.lower()
    return all(n.lower() in haystack for n in needles)


class TestTheUserOutranksThePersona:
    def test_it_states_that_an_explicit_tone_request_wins(self, soul: str) -> None:
        """The rule has to be stated as a rule, not as an example."""
        assert _has(
            soul,
            "what the user tells me about how to talk",
            "beats",
        ), "the persona must state that the user's tone instruction outranks its own"

    def test_it_names_the_exact_words_the_failure_took_as_a_joke(self, soul: str) -> None:
        """The two words from the real failure. Without them the model has no
        anchor for the case, and defaults to defending the bit."""
        assert _has(soul, "be professional", "stop joking"), (
            "the persona must cover the literal phrases a user would type"
        )

    def test_switching_is_immediate_and_sticks(self, soul: str) -> None:
        assert _has(soul, "immediately"), "the switch must be immediate, not deferred"
        assert _has(soul, "until they release"), "the register must persist until released"

    def test_it_refuses_to_negotiate_the_instruction(self, soul: str) -> None:
        """The failure was a joke *about* being told to be serious. That is the
        loophole to close by name."""
        assert _has(soul, "not a joke about being told to be serious"), (
            "the persona must rule out joking about the tone instruction itself"
        )
        assert _has(soul, "never make the user ask twice"), (
            "a refused tone instruction is the defect; say it cannot happen"
        )


class TestPlayfulIsADefaultNotACostume:
    def test_both_registers_exist(self, soul: str) -> None:
        assert _has(soul, "playful"), "the playful register must be named"
        assert _has(soul, "serious"), "the serious register must be named"

    def test_the_choice_is_made_per_turn_not_worn_permanently(self, soul: str) -> None:
        assert _has(soul, "every turn"), (
            "the register must be a per-turn decision, not one costume"
        )

    def test_real_work_selects_serious(self, soul: str) -> None:
        assert _has(
            soul,
            "debugging",
            "serious",
        ), "the persona must say what selects the serious register"

    def test_it_returns_to_playful_when_the_work_is_over(self, soul: str) -> None:
        assert _has(soul, "back to playful"), "work mode must not be permanent"


class TestRudeHasEdges:
    """A joke that can land on the wrong thing is not a personality, and the
    user asked for rude — not for cruelty."""

    def test_it_aims_at_the_user_not_below_the_belt(self, soul: str) -> None:
        assert _has(soul, "never aim below the belt"), (
            "rude must be bounded at the user's vulnerabilities"
        )

    def test_people_not_in_the_room_are_off_limits(self, soul: str) -> None:
        assert _has(soul, "never mock people who aren't in the room"), (
            "third parties must be protected from the bit"
        )

    def test_it_stands_down_when_something_is_wrong(self, soul: str) -> None:
        assert _has(soul, "get cute when something is actually wrong"), (
            "humour must switch off when the user is stressed or the news is bad"
        )

    def test_the_joke_never_substitutes_for_the_answer(self, soul: str) -> None:
        assert _has(soul, "never stand in for the answer"), (
            "a joke must not replace the deliverable"
        )


class TestCompanyDuringLongWork:
    def test_it_stays_present_while_work_runs(self, soul: str) -> None:
        assert _has(soul, "while something long runs"), (
            "the persona must cover behaviour during long operations"
        )

    def test_progress_chatter_must_not_delay_or_replace_the_work(self, soul: str) -> None:
        assert _has(soul, "never a reason to delay"), (
            "humour must never delay or skip the actual work"
        )

    def test_failure_stops_the_bit_and_names_the_break(self, soul: str) -> None:
        assert _has(soul, "joke stops"), "on failure the persona must drop the bit"
        assert _has(soul, "what broke"), "on failure it must say what broke"


class TestExistingInstallsReceiveIt:
    """``SOUL.md`` is not in ``_BOOTSTRAP_SKIP_IF_TEMPLATE`` — the persona stays
    in the prompt — so editing the template alone would fix only new installs and
    every phone already carrying the old copy would keep the defect forever. The
    retirement table is what makes the fix reach them."""

    def test_the_previous_persona_is_retired(self) -> None:
        retired = _RETIRED_TEMPLATE_DIGESTS.get("SOUL.md", {})
        assert (
            "e80febe4e68a587c9544815a44fe9207e1c3b2534ade9891395f31ef71b859c7" in retired
        ), "the shipped single-register persona must be in the retirement table"

    def test_the_current_persona_is_not_retired(self, soul: str) -> None:
        """Retiring the live version would rewrite it forever and never converge."""
        retired = _RETIRED_TEMPLATE_DIGESTS.get("SOUL.md", {})
        assert template_digest(soul) not in retired, (
            "the current SOUL.md must not match a retired digest"
        )
