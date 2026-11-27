"""Link-based grouping: documents that point at one page are one story (ADR-003, RFC §4
step 6).

This is the M1 rule and it is deterministic. A document that passed screening joins the
story of an earlier document with the same canonical address; otherwise it starts a story
of its own. That covers a post and the discussion of it: a Hacker News item is stored
under the address it links to, so it lands in the story of the post it discusses.

Every change is an append-only membership event that names the rule that made it. Only a
document with no story is ever placed, so grouping again changes nothing.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.engine import Connection

from ai_briefing.domain.enums import MembershipAction
from ai_briefing.domain.records import Story, StoryMembershipEvent
from ai_briefing.storage import queries, repositories
from ai_briefing.stories.canonical import canonical_url

OWN_STORY_RULE = "own-story"
SAME_URL_RULE = "same-url"


def group(connection: Connection, now: datetime) -> dict[str, int]:
    """Place every document that passed screening and has no story. Returns how many
    stories were started and how many documents joined an existing one.
    """
    counts = {"stories_started": 0, "documents_joined": 0}
    # The earliest open story for each address. A later document joins that one.
    by_address: dict[str, int] = {}
    for open_story, url in queries.open_story_addresses(connection):
        address = canonical_url(url)
        if address is not None:
            by_address.setdefault(address, open_story)
    for document in queries.passed_documents_without_story(connection):
        if document.id is None:
            continue
        key = canonical_url(document.canonical_url)
        joined = by_address.get(key) if key is not None else None
        if joined is None:
            story = repositories.add(
                connection, Story(title=document.title, first_seen_at=now, last_activity_at=now)
            )
            if story.id is None:
                continue
            story_id = story.id
            reason = "a document that passed screening starts its own story"
            rule = OWN_STORY_RULE
            counts["stories_started"] += 1
            if key is not None:
                by_address[key] = story_id
        else:
            story_id = joined
            reason = "its address is the address of a document already in this story"
            rule = SAME_URL_RULE
            counts["documents_joined"] += 1
        repositories.record_membership(
            connection,
            StoryMembershipEvent(
                story_id=story_id,
                document_id=document.id,
                action=MembershipAction.ADD,
                reason=reason,
                decided_by_rule=rule,
                occurred_at=now,
            ),
        )
    return counts
