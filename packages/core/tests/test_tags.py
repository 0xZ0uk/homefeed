from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.curation import subscribe_tag, tag_subscription
from homefeed_core.db import open_database
from homefeed_core.embeddings import StubEmbeddingProvider
from homefeed_core.tags import (
    DuplicateTagError,
    ProposedTag,
    SameTagError,
    Tag,
    VideoTag,
    add_manual_tag,
    clean_label,
    find_tag,
    get_tag,
    get_video_tags,
    is_usable,
    list_admin_tags,
    merge_tags,
    refresh_tag_embeddings,
    remove_video_tag,
    rename_tag,
    resolve_tag,
    set_llm_tags,
    slugify,
    split_alias,
    suggest_tags,
    top_tag_labels,
)

NOW = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
VIDEO = "aaaaaaaaaaa"
OTHER = "bbbbbbbbbbb"


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES ('UCx', 'Channel')"))
        for video_id in (VIDEO, OTHER):
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, 'UCx', :id)"),
                {"id": video_id},
            )
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def aliases(session: Session) -> dict[str, str]:
    """alias -> slug of its tag."""
    rows = session.execute(
        text("SELECT a.alias, t.slug FROM tag_aliases AS a JOIN tags AS t ON t.id = a.tag_id")
    )
    return {alias: slug for alias, slug in rows}


def links(session: Session, video_id: str) -> list[tuple[str, str, float, int | None, bool]]:
    """(slug, source, confidence, prompt_version, removed) of every link, tombstones too."""
    rows = session.execute(
        text(
            """
            SELECT t.slug, vt.source, vt.confidence, vt.prompt_version, vt.removed_at IS NOT NULL
            FROM video_tags AS vt JOIN tags AS t ON t.id = vt.tag_id
            WHERE vt.video_id = :video_id ORDER BY t.slug
            """
        ),
        {"video_id": video_id},
    )
    return [
        (slug, source, conf, version, bool(removed))
        for slug, source, conf, version, removed in rows
    ]


# Normalization


@pytest.mark.parametrize(
    ("spelling", "slug"),
    [
        ("rust", "rust"),
        ("Rust", "rust"),
        ("  Dovetail   Joints ", "dovetail-joints"),
        ("#woodworking", "woodworking"),
        ("F1", "f1"),
        ("Formula 1", "formula-1"),
        ("Pokémon", "pokemon"),
        ("C++", "c-plus-plus"),
        ("C#", "c-sharp"),
        ("rock & roll", "rock-and-roll"),
        ("Node.js", "node-js"),
        ("women's football", "womens-football"),
        ("snake_case", "snake-case"),
        ("ゲーム", "ゲーム"),  # kana voicing marks are kept
        ("!!!", ""),
    ],
)
def test_slugify(spelling: str, slug: str) -> None:
    assert slugify(spelling) == slug


def test_labels_and_usable_spellings() -> None:
    assert clean_label("  #Dovetail\n joints ") == "Dovetail joints"
    assert is_usable("rust")
    assert not is_usable("  ")
    assert not is_usable("?!")
    assert not is_usable("x" * 51)


# Resolution


def test_new_spellings_create_tags(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        tag = resolve_tag(session, " Dovetail joints ", now=NOW)

        assert tag is not None
        assert (tag.slug, tag.label) == ("dovetail-joints", "Dovetail joints")
        assert get_tag(session, "dovetail-joints") == tag
        assert resolve_tag(session, "!!!") is None


def test_the_same_slug_resolves_to_the_same_tag(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first = resolve_tag(session, "Rust")
        again = resolve_tag(session, "rust")

        assert again == first
        assert session.execute(text("SELECT count(*) FROM tags")).scalar() == 1
        assert aliases(session) == {}


def test_aliases_resolve_to_their_tag(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rust = resolve_tag(session, "rust")
        assert rust is not None
        session.execute(
            text(
                "INSERT INTO tag_aliases (alias, tag_id, source) VALUES ('rust-lang', :id, 'user')"
            ),
            {"id": rust.id},
        )

        assert resolve_tag(session, "Rust Lang") == rust
        assert find_tag(session, "rust-lang") == rust
        assert session.execute(text("SELECT count(*) FROM tags")).scalar() == 1


def test_spellings_differing_in_hyphens_share_a_tag_and_become_aliases(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        woodworking = resolve_tag(session, "woodworking")
        assert find_tag(session, "wood working") == woodworking  # found, nothing written
        assert aliases(session) == {}

        assert resolve_tag(session, "Wood-Working") == woodworking
        assert aliases(session) == {"wood-working": "woodworking"}
        # Later spellings match through the alias as well as the slug.
        nodejs = resolve_tag(session, "node-js")
        assert resolve_tag(session, "nodejs") == nodejs
        assert aliases(session) == {"wood-working": "woodworking", "nodejs": "node-js"}


def test_find_tag_does_not_create(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert find_tag(session, "rust") is None
        assert session.execute(text("SELECT count(*) FROM tags")).scalar() == 0


# Video tags


def test_set_llm_tags_links_resolved_tags(sessions: sessionmaker[Session]) -> None:
    proposals = [
        ProposedTag("hand tools", 0.6),
        ProposedTag("Woodworking", 0.9),
        ProposedTag("wood-working", 0.7),  # the same tag: the higher confidence stays
        ProposedTag("???", 0.8),  # unusable
    ]
    with sessions.begin() as session:
        tags = set_llm_tags(session, VIDEO, proposals, prompt_version=2, now=NOW)

        assert [tag.slug for tag in tags] == ["woodworking", "hand-tools"]
        assert links(session, VIDEO) == [
            ("hand-tools", "llm", 0.6, 2, False),
            ("woodworking", "llm", 0.9, 2, False),
        ]
        assert get_video_tags(session, [VIDEO, OTHER]) == {
            VIDEO: [
                VideoTag(tags[0].id, "woodworking", "Woodworking", "llm", 0.9),
                VideoTag(tags[1].id, "hand-tools", "hand tools", "llm", 0.6),
            ]
        }


def test_retagging_replaces_llm_tags(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_llm_tags(
            session, VIDEO, [ProposedTag("rust", 0.9), ProposedTag("cargo", 0.5)], prompt_version=2
        )
        set_llm_tags(
            session,
            VIDEO,
            [ProposedTag("rust", 0.8), ProposedTag("embedded", 0.7)],
            prompt_version=3,
        )

        assert links(session, VIDEO) == [
            ("embedded", "llm", 0.7, 3, False),
            ("rust", "llm", 0.8, 3, False),
        ]
        # The tag itself stays in the vocabulary.
        assert get_tag(session, "cargo") is not None

        set_llm_tags(session, VIDEO, [], prompt_version=3)
        assert links(session, VIDEO) == []


def test_retagging_keeps_manual_tags_and_tombstones(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_llm_tags(
            session, VIDEO, [ProposedTag("rust", 0.9), ProposedTag("cargo", 0.5)], prompt_version=2
        )
        manual = resolve_tag(session, "embedded")
        assert isinstance(manual, Tag)
        session.execute(
            text(
                """
                INSERT INTO video_tags (video_id, tag_id, source, confidence)
                VALUES (:video, :tag, 'manual', 1)
                """
            ),
            {"video": VIDEO, "tag": manual.id},
        )
        cargo = get_tag(session, "cargo")
        assert cargo is not None
        session.execute(
            text(
                "UPDATE video_tags SET removed_at = '2026-10-12T00:00:00.000Z' WHERE tag_id = :id"
            ),
            {"id": cargo.id},
        )

        set_llm_tags(
            session,
            VIDEO,
            [ProposedTag("cargo", 0.9), ProposedTag("embedded", 0.4)],
            prompt_version=3,
        )

        assert links(session, VIDEO) == [
            ("cargo", "llm", 0.5, 2, True),  # still removed, unchanged
            ("embedded", "manual", 1.0, None, False),  # still manual
        ]
        assert [tag.slug for tag in get_video_tags(session, [VIDEO])[VIDEO]] == ["embedded"]


# Embedding matches

# Four-dimensional vectors with chosen similarities to "Rust": "rust lang" is 0.95 close
# (a merge), "Rust game" is 0.8 (the other Rust, a near-miss under the 0.92 threshold).
RUST_VECTORS = {
    "Rust": [1.0, 0.0, 0.0, 0.0],
    "rust lang": [0.95, 0.312_249_9, 0.0, 0.0],
    "Rust game": [0.8, 0.6, 0.0, 0.0],
    "Baking": [0.0, 0.0, 1.0, 0.0],
}


def rust_embedder(model: str = "stub-embedding-v1") -> StubEmbeddingProvider:
    return StubEmbeddingProvider(model, dimensions=4, vectors=RUST_VECTORS)


def embedding_models(session: Session) -> dict[str, str | None]:
    rows = session.execute(text("SELECT slug, embedding_model FROM tags"))
    return {slug: model for slug, model in rows}


def test_new_tags_are_stored_with_their_embedding(sessions: sessionmaker[Session]) -> None:
    embedder = rust_embedder()

    with sessions.begin() as session:
        resolve_tag(session, "Rust", embedder=embedder)
        resolve_tag(session, "rust", embedder=embedder)  # a slug match: not embedded again

    with sessions() as session:
        assert embedding_models(session) == {"rust": "stub-embedding-v1"}
    assert embedder.calls == [["Rust"]]


def test_a_similar_spelling_merges_into_the_tag_as_an_alias(
    sessions: sessionmaker[Session],
) -> None:
    embedder = rust_embedder()
    with sessions.begin() as session:
        rust = resolve_tag(session, "Rust", embedder=embedder)
        merged = resolve_tag(session, "rust lang", embedder=embedder)
        again = resolve_tag(session, "rust lang", embedder=embedder)

    assert rust is not None and merged == rust and again == rust
    with sessions() as session:
        assert aliases(session) == {"rust-lang": "rust"}
        assert session.execute(text("SELECT source FROM tag_aliases")).scalar_one() == "auto"
        assert embedding_models(session) == {"rust": "stub-embedding-v1"}
    assert embedder.calls == [["Rust"], ["rust lang"]]  # the alias answers the second time


def test_a_near_miss_stays_a_separate_tag(sessions: sessionmaker[Session]) -> None:
    embedder = rust_embedder()
    with sessions.begin() as session:
        rust = resolve_tag(session, "Rust", embedder=embedder)
        game = resolve_tag(session, "Rust game", embedder=embedder)

    assert rust is not None and game is not None and game.id != rust.id
    with sessions() as session:
        assert aliases(session) == {}
        assert embedding_models(session) == {
            "rust": "stub-embedding-v1",
            "rust-game": "stub-embedding-v1",
        }


def test_the_threshold_is_configurable(sessions: sessionmaker[Session]) -> None:
    embedder = rust_embedder()
    with sessions.begin() as session:
        rust = resolve_tag(session, "Rust", embedder=embedder)
        game = resolve_tag(session, "Rust game", embedder=embedder, threshold=0.75)
        strict = resolve_tag(session, "rust lang", embedder=embedder, threshold=0.99)

    assert game == rust
    assert strict is not None and strict.slug == "rust-lang"


def test_user_aliases_win_over_similarity(sessions: sessionmaker[Session]) -> None:
    embedder = rust_embedder()
    with sessions.begin() as session:
        rust = resolve_tag(session, "Rust", embedder=embedder)
        baking = resolve_tag(session, "Baking", embedder=embedder)
        assert rust is not None and baking is not None
        session.execute(
            text(
                "INSERT INTO tag_aliases (alias, tag_id, source) VALUES ('rust-lang', :id, 'user')"
            ),
            {"id": baking.id},
        )
        resolved = resolve_tag(session, "rust lang", embedder=embedder)

    assert resolved == baking
    assert embedder.calls == [["Rust"], ["Baking"]]


def test_tags_without_an_embedding_or_with_another_model_do_not_match(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        resolve_tag(session, "Rust")  # made without an embedder
        old = resolve_tag(session, "Baking", embedder=rust_embedder("stub-embedding-v0"))
        assert old is not None
        result = resolve_tag(session, "rust lang", embedder=rust_embedder())

    assert result is not None and result.slug == "rust-lang"


def test_embedding_failure_still_resolves_tags(sessions: sessionmaker[Session]) -> None:
    class Broken(StubEmbeddingProvider):
        def embed(self, texts):  # type: ignore[no-untyped-def]
            raise RuntimeError("model unavailable")

    with sessions.begin() as session:
        tag = resolve_tag(session, "Rust", embedder=Broken())
        assert tag is not None
        assert embedding_models(session) == {"rust": None}
        refreshed = refresh_tag_embeddings(session, rust_embedder())

    assert refreshed == [tag.id]
    with sessions() as session:
        assert embedding_models(session) == {"rust": "stub-embedding-v1"}


def test_set_llm_tags_embeds_all_proposals_in_one_call(sessions: sessionmaker[Session]) -> None:
    embedder = rust_embedder()
    with sessions.begin() as session:
        resolve_tag(session, "Rust", embedder=embedder)
    embedder.calls.clear()

    with sessions.begin() as session:
        tags = set_llm_tags(
            session,
            VIDEO,
            [
                ProposedTag("rust lang", 0.9),
                ProposedTag("Rust game", 0.8),
                ProposedTag("Baking", 0.7),
                ProposedTag("rust", 0.6),  # a slug match: not embedded
            ],
            prompt_version=1,
            embedder=embedder,
        )

    assert [t.slug for t in tags] == ["rust", "rust-game", "baking"]
    assert embedder.calls == [["rust lang", "Rust game", "Baking"]]


def test_refresh_tag_embeddings_after_a_model_change(sessions: sessionmaker[Session]) -> None:
    embedder = rust_embedder()
    with sessions.begin() as session:
        resolve_tag(session, "Rust", embedder=embedder)
        resolve_tag(session, "Baking")
    other = rust_embedder("stub-embedding-v2")

    with sessions.begin() as session:
        refreshed = refresh_tag_embeddings(session, other)
        assert refresh_tag_embeddings(session, other) == []
        models = embedding_models(session)
        merged = resolve_tag(session, "rust lang", embedder=other)

    assert len(refreshed) == 2
    assert models == {"rust": "stub-embedding-v2", "baking": "stub-embedding-v2"}
    assert merged is not None and merged.slug == "rust"


def test_top_tag_labels_by_video_count_without_removed_links(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        for video_id, labels in ((VIDEO, ["Rust", "Baking", "Chess"]), (OTHER, ["Rust", "Baking"])):
            set_llm_tags(
                session, video_id, [ProposedTag(label, 0.9) for label in labels], prompt_version=1
            )
        session.execute(
            text(
                "UPDATE video_tags SET removed_at = '2026-10-13T00:00:00.000Z' "
                "WHERE video_id = :video AND tag_id = (SELECT id FROM tags WHERE slug = 'baking')"
            ),
            {"video": OTHER},
        )
        session.execute(text("INSERT INTO tags (slug, label) VALUES ('unused', 'Unused')"))

        assert top_tag_labels(session, 2) == ["Baking", "Rust"]
        assert top_tag_labels(session, 10) == ["Baking", "Chess", "Rust"]


def test_add_manual_tag_resolves_and_links_with_confidence_one(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        set_llm_tags(session, VIDEO, [ProposedTag("Woodworking", 0.7)], prompt_version=2)

        tag = add_manual_tag(session, VIDEO, "  #Wood-working ")  # an alias of the tag

        assert tag == get_tag(session, "woodworking")
        assert links(session, VIDEO) == [("woodworking", "manual", 1.0, None, False)]
        new = add_manual_tag(session, VIDEO, "Hand Tools")
        assert new is not None and new.slug == "hand-tools"
        assert [t.slug for t in get_video_tags(session, [VIDEO])[VIDEO]] == [
            "hand-tools",
            "woodworking",
        ]
        assert add_manual_tag(session, VIDEO, "***") is None
        assert add_manual_tag(session, VIDEO, "x" * 60) is None


def test_manual_tags_survive_retagging(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_manual_tag(session, VIDEO, "rust")  # also proposed by the LLM
        add_manual_tag(session, VIDEO, "embedded")
        set_llm_tags(session, VIDEO, [ProposedTag("rust", 0.4)], prompt_version=3)

        assert links(session, VIDEO) == [
            ("embedded", "manual", 1.0, None, False),
            ("rust", "manual", 1.0, None, False),
        ]


def test_removed_tags_are_tombstoned_and_not_re_added(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_llm_tags(
            session, VIDEO, [ProposedTag("rust", 0.9), ProposedTag("cargo", 0.5)], prompt_version=2
        )
        add_manual_tag(session, VIDEO, "embedded")

        assert remove_video_tag(session, VIDEO, "cargo")
        assert remove_video_tag(session, VIDEO, "embedded")  # manual tags too
        assert not remove_video_tag(session, VIDEO, "cargo")  # already removed
        assert not remove_video_tag(session, VIDEO, "nope")
        assert not remove_video_tag(session, OTHER, "rust")  # not on that video

        set_llm_tags(
            session,
            VIDEO,
            [ProposedTag("cargo", 0.9), ProposedTag("embedded", 0.9), ProposedTag("rust", 0.8)],
            prompt_version=3,
        )

        assert [t.slug for t in get_video_tags(session, [VIDEO])[VIDEO]] == ["rust"]
        assert [(slug, removed) for slug, _, _, _, removed in links(session, VIDEO)] == [
            ("cargo", True),
            ("embedded", True),
            ("rust", False),
        ]


def test_adding_a_removed_tag_back_makes_it_manual(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_llm_tags(session, VIDEO, [ProposedTag("cargo", 0.5)], prompt_version=2)
        remove_video_tag(session, VIDEO, "cargo")

        add_manual_tag(session, VIDEO, "Cargo")
        set_llm_tags(session, VIDEO, [], prompt_version=3)

        assert links(session, VIDEO) == [("cargo", "manual", 1.0, None, False)]


def test_suggest_tags_matches_slugs_and_aliases_by_prefix_then_use(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        set_llm_tags(
            session,
            VIDEO,
            [ProposedTag("rust", 0.9), ProposedTag("trust falls", 0.5), ProposedTag("go", 0.5)],
            prompt_version=2,
        )
        set_llm_tags(session, OTHER, [ProposedTag("trust falls", 0.5)], prompt_version=2)
        resolve_tag(session, "rustlang")
        remove_video_tag(session, OTHER, "trust-falls")

        assert [(s.slug, s.video_count) for s in suggest_tags(session, "Rus")] == [
            ("rust", 1),
            ("rustlang", 0),
            ("trust-falls", 1),
        ]
        assert [s.slug for s in suggest_tags(session, "", limit=2)] == ["go", "rust"]
        assert suggest_tags(session, "100%") == []


def link(
    session: Session,
    video_id: str,
    tag: Tag,
    *,
    source: str = "llm",
    confidence: float = 0.5,
    removed: bool = False,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO video_tags (video_id, tag_id, source, confidence, removed_at)
            VALUES (:video, :tag, :source, :confidence, :removed)
            """
        ),
        {
            "video": video_id,
            "tag": tag.id,
            "source": source,
            "confidence": confidence,
            "removed": "2026-10-13T06:00:00.000Z" if removed else None,
        },
    )


def alias_sources(session: Session) -> dict[str, str]:
    return {a: s for a, s in session.execute(text("SELECT alias, source FROM tag_aliases"))}


def test_rename_changes_label_and_slug_and_keeps_the_old_slug_as_a_user_alias(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        tag = resolve_tag(session, "wood work")
        assert tag is not None

        renamed = rename_tag(session, tag.id, " Woodworking ")

        assert renamed == Tag(tag.id, "woodworking", "Woodworking")
        assert get_tag(session, "wood-work") is None
        assert aliases(session) == {"wood-work": "woodworking"}
        assert alias_sources(session) == {"wood-work": "user"}
        assert resolve_tag(session, "Wood work") == renamed
        assert rename_tag(session, 999, "x") is None


def test_rename_label_only_keeps_the_slug(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        tag = resolve_tag(session, "f1")
        assert tag is not None

        assert rename_tag(session, tag.id, "F1") == Tag(tag.id, "f1", "F1")
        assert aliases(session) == {}


def test_rename_to_another_tags_slug_or_alias_is_refused(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        rust = resolve_tag(session, "rust")
        go = resolve_tag(session, "go")
        assert rust is not None and go is not None
        session.execute(
            text("INSERT INTO tag_aliases (alias, tag_id, source) VALUES ('golang', :id, 'auto')"),
            {"id": go.id},
        )

        with pytest.raises(DuplicateTagError):
            rename_tag(session, rust.id, "Go")
        with pytest.raises(DuplicateTagError):
            rename_tag(session, rust.id, "GoLang")
        with pytest.raises(ValueError, match="at most"):
            rename_tag(session, rust.id, "!!!")
        assert get_tag(session, "rust") == rust


def test_rename_to_its_own_alias_drops_that_alias(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        tag = resolve_tag(session, "rust")
        assert tag is not None
        session.execute(
            text(
                "INSERT INTO tag_aliases (alias, tag_id, source) VALUES ('rustlang', :id, 'auto')"
            ),
            {"id": tag.id},
        )

        rename_tag(session, tag.id, "Rustlang")

        assert aliases(session) == {"rust": "rustlang"}


def test_rename_reembeds_or_clears_the_embedding(sessions: sessionmaker[Session]) -> None:
    embedder = StubEmbeddingProvider()
    with sessions.begin() as session:
        tag = resolve_tag(session, "wood work", embedder=embedder)
        assert tag is not None

        rename_tag(session, tag.id, "Woodworking", embedder=embedder)
        assert embedder.calls[-1] == ["Woodworking"]
        assert session.execute(
            text("SELECT embedding IS NOT NULL, embedding_model FROM tags")
        ).one() == (1, embedder.model)

        rename_tag(session, tag.id, "Carpentry")
        assert session.execute(text("SELECT embedding, embedding_model FROM tags")).one() == (
            None,
            None,
        )
        assert refresh_tag_embeddings(session, embedder) == [tag.id]


def test_merge_moves_spellings_and_links(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        js = resolve_tag(session, "javascript")
        node = resolve_tag(session, "node")
        assert js is not None and node is not None
        session.execute(
            text("INSERT INTO tag_aliases (alias, tag_id, source) VALUES ('nodejs', :id, 'auto')"),
            {"id": node.id},
        )
        link(session, VIDEO, node)
        link(session, OTHER, js)

        assert merge_tags(session, node.id, js.id) == js

        assert get_tag(session, "node") is None
        assert alias_sources(session) == {"node": "user", "nodejs": "user"}
        assert aliases(session) == {"node": "javascript", "nodejs": "javascript"}
        assert links(session, VIDEO) == [("javascript", "llm", 0.5, None, False)]
        assert resolve_tag(session, "node") == js
        assert resolve_tag(session, "nodejs") == js


def test_merge_moves_the_subscription_unless_the_target_has_one(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        rust, cargo, ferris = (resolve_tag(session, label) for label in ("rust", "cargo", "ferris"))
        assert rust is not None and cargo is not None and ferris is not None
        subscribe_tag(session, rust, weight=0.3)
        subscribe_tag(session, cargo, weight=-0.5)

        # Both have one: the target's stands, the source's goes.
        merge_tags(session, cargo.id, rust.id)
        kept = tag_subscription(session, rust.id)
        assert kept is not None and kept.weight == 0.3
        assert tag_subscription(session, cargo.id) is None

        # Only the source has one: it follows to the target.
        merge_tags(session, rust.id, ferris.id)
        moved = tag_subscription(session, ferris.id)
        assert moved is not None and moved.weight == 0.3
        assert tag_subscription(session, rust.id) is None


def test_merge_keeps_one_link_per_video(sessions: sessionmaker[Session]) -> None:
    other = "ccccccccccc"
    third = "ddddddddddd"
    fourth = "eeeeeeeeeee"
    with sessions.begin() as session:
        for video_id in (other, third, fourth):
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, 'UCx', :id)"),
                {"id": video_id},
            )
        src = resolve_tag(session, "src")
        dst = resolve_tag(session, "dst")
        assert src is not None and dst is not None
        # Manual beats LLM, whichever side it is on.
        link(session, VIDEO, src, source="manual", confidence=1)
        link(session, VIDEO, dst, confidence=0.9)
        link(session, OTHER, src, confidence=0.9)
        link(session, OTHER, dst, source="manual", confidence=1)
        # An active manual link wins over a tombstone; a tombstone over an LLM link.
        link(session, other, src, removed=True)
        link(session, other, dst, source="manual", confidence=1)
        link(session, third, src, confidence=0.9)
        link(session, third, dst, removed=True)
        # The higher confidence wins between two LLM links.
        link(session, fourth, src, confidence=0.8)
        link(session, fourth, dst, confidence=0.6)

        merge_tags(session, src.id, dst.id)

        assert links(session, VIDEO) == [("dst", "manual", 1.0, None, False)]
        assert links(session, OTHER) == [("dst", "manual", 1.0, None, False)]
        assert links(session, other) == [("dst", "manual", 1.0, None, False)]
        assert links(session, third) == [("dst", "llm", 0.5, None, True)]
        assert links(session, fourth) == [("dst", "llm", 0.8, None, False)]
        assert session.execute(text("SELECT count(*) FROM video_tags")).scalar() == 5


def test_merge_chains_aliases_and_beats_the_embedding_match(
    sessions: sessionmaker[Session],
) -> None:
    # "js" is closest to typescript by embedding, but merging it into javascript wins.
    embedder = StubEmbeddingProvider(
        vectors={"js": (1, 0, 0), "typescript": (1, 0.01, 0), "javascript": (0, 1, 0)}
    )
    with sessions.begin() as session:
        ts = resolve_tag(session, "typescript", embedder=embedder)
        js = resolve_tag(session, "javascript", embedder=embedder)
        short = resolve_tag(session, "js", embedder=embedder, threshold=2)
        assert ts is not None and js is not None and short is not None
        assert short.id not in (ts.id, js.id)
        merge_tags(session, short.id, js.id)
        merge_tags(session, js.id, ts.id)  # and again: aliases follow the chain
        assert alias_sources(session) == {"js": "user", "javascript": "user"}

        assert resolve_tag(session, "js", embedder=embedder) == ts
        assert get_tag(session, "javascript") is None


def test_merge_rejects_the_same_or_missing_tags(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        tag = resolve_tag(session, "rust")
        assert tag is not None
        with pytest.raises(SameTagError):
            merge_tags(session, tag.id, tag.id)
        assert merge_tags(session, tag.id, 999) is None
        assert merge_tags(session, 999, tag.id) is None
        assert get_tag(session, "rust") == tag


def test_split_makes_the_alias_its_own_tag(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        js = resolve_tag(session, "javascript")
        assert js is not None
        session.execute(
            text("INSERT INTO tag_aliases (alias, tag_id, source) VALUES ('node-js', :id, 'user')"),
            {"id": js.id},
        )
        link(session, VIDEO, js)

        node = split_alias(session, "node-js")

        assert node is not None
        assert (node.slug, node.label) == ("node-js", "node js")
        assert aliases(session) == {}
        assert resolve_tag(session, "Node.js") == node
        assert links(session, VIDEO) == [("javascript", "llm", 0.5, None, False)]
        assert split_alias(session, "node-js") is None


def test_split_overrides_the_embedding_match(sessions: sessionmaker[Session]) -> None:
    embedder = StubEmbeddingProvider(vectors={"js": (1, 0), "javascript": (1, 0.01)})
    with sessions.begin() as session:
        js = resolve_tag(session, "javascript", embedder=embedder)
        assert js is not None
        # "js" folds into javascript by similarity, recording an auto alias.
        assert resolve_tag(session, "js", embedder=embedder) == js
        assert aliases(session) == {"js": "javascript"}

        short = split_alias(session, "js", embedder=embedder)

        assert short is not None and short.id != js.id
        assert session.execute(
            text("SELECT embedding IS NOT NULL FROM tags WHERE id = :id"), {"id": short.id}
        ).scalar()
        assert resolve_tag(session, "js", embedder=embedder) == short
        assert resolve_tag(session, "JS", embedder=embedder) == short
        assert aliases(session) == {}


def test_list_admin_tags_counts_and_searches(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rust = resolve_tag(session, "Rust")
        wood = resolve_tag(session, "Wood Working")
        assert rust is not None and wood is not None
        session.execute(
            text(
                "INSERT INTO tag_aliases (alias, tag_id, source) VALUES ('rust-lang', :id, 'auto')"
            ),
            {"id": rust.id},
        )
        link(session, VIDEO, rust)
        link(session, OTHER, rust, removed=True)
        link(session, OTHER, wood)
        link(session, VIDEO, wood)

        everything = list_admin_tags(session)
        assert [(t.slug, t.video_count) for t in everything] == [
            ("wood-working", 2),
            ("rust", 1),
        ]
        assert [(a.alias, a.source) for a in everything[1].aliases] == [("rust-lang", "auto")]
        assert [t.slug for t in list_admin_tags(session, "LANG")] == ["rust"]
        assert [t.slug for t in list_admin_tags(session, "wood work")] == ["wood-working"]
        assert list_admin_tags(session, "100%") == []
        assert len(list_admin_tags(session, limit=1)) == 1
        assert all(t.subscription_weight is None for t in everything)

        subscribe_tag(session, wood, weight=0.0)
        subscribe_tag(session, rust, weight=-0.5)
        assert [(t.slug, t.subscription_weight) for t in list_admin_tags(session)] == [
            ("wood-working", 0.0),
            ("rust", -0.5),
        ]
        assert [t.slug for t in list_admin_tags(session, subscription="subscribed")] == [
            "wood-working"
        ]
        assert [t.slug for t in list_admin_tags(session, subscription="muted")] == ["rust"]
        assert list_admin_tags(session, "wood", subscription="muted") == []
