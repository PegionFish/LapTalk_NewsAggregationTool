from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from config import config
from db.news_db import NewsDB

router = APIRouter(prefix="/api/chains", tags=["chains"])

def get_db() -> NewsDB:
    path = config.db_path
    if not path:
        raise HTTPException(400, "database_not_configured")
    return NewsDB(path)

@router.get("")
def list_chains():
    db = get_db()
    with db._conn() as conn:
        rows = conn.execute("""
            SELECT c.id, c.title, c.description, c.created_at, c.updated_at, c.created_by,
                   (SELECT COUNT(*) FROM chain_events WHERE chain_id=c.id) as event_count
            FROM logic_chains c ORDER BY c.updated_at DESC
        """).fetchall()
    return {'chains': [
        {'id': r[0], 'title': r[1], 'description': r[2], 'created_at': r[3],
         'updated_at': r[4], 'created_by': r[5], 'event_count': r[6]}
        for r in rows
    ]}

class CreateChain(BaseModel):
    title: str
    description: str = ''
    event_ids: list[int] = []

@router.post("")
def create_chain(body: CreateChain):
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        cur = conn.execute(
            "INSERT INTO logic_chains (title, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (body.title, body.description, now, now)
        )
        chain_id = cur.lastrowid
        for pos, eid in enumerate(body.event_ids):
            conn.execute(
                "INSERT INTO chain_events (chain_id, event_id, position) VALUES (?, ?, ?)",
                (chain_id, eid, pos)
            )
        conn.commit()
    return {'id': chain_id, 'title': body.title}

@router.get("/{chain_id}")
def get_chain(chain_id: int):
    """Get chain with full event tree including sub-chains."""
    db = get_db()
    with db._conn() as conn:
        chain = conn.execute(
            "SELECT id, title, description, created_at, updated_at, created_by FROM logic_chains WHERE id=?",
            (chain_id,)
        ).fetchone()
        if not chain:
            raise HTTPException(404, "chain_not_found")

        # Get direct events
        events = conn.execute("""
            SELECT e.id, e.title, e.first_seen, e.last_seen, e.article_count, ce.position, ce.note
            FROM chain_events ce
            JOIN events e ON e.id = ce.event_id
            WHERE ce.chain_id=?
            ORDER BY ce.position
        """, (chain_id,)).fetchall()

        # Get sub-chains
        sub_chains = conn.execute("""
            SELECT lc.id, lc.title, cr.position
            FROM chain_relations cr
            JOIN logic_chains lc ON lc.id = cr.child_chain_id
            WHERE cr.parent_chain_id=?
            ORDER BY cr.position
        """, (chain_id,)).fetchall()

    return {
        'id': chain[0], 'title': chain[1], 'description': chain[2],
        'created_at': chain[3], 'updated_at': chain[4], 'created_by': chain[5],
        'events': [
            {'id': r[0], 'title': r[1], 'first_seen': r[2], 'last_seen': r[3],
             'article_count': r[4], 'position': r[5], 'note': r[6]}
            for r in events
        ],
        'sub_chains': [
            {'id': r[0], 'title': r[1], 'position': r[2]} for r in sub_chains
        ]
    }

@router.get("/{chain_id}/timeline")
def get_chain_timeline(chain_id: int):
    """Recursively expand sub-chains into a single merged event timeline.
    Returns a flat list ordered by (sub_chain_position, event_position).
    Front-end uses this to render the full narrative in one request."""
    db = get_db()
    with db._conn() as conn:
        chain = conn.execute("SELECT id, title FROM logic_chains WHERE id=?", (chain_id,)).fetchone()
        if not chain:
            raise HTTPException(404, "chain_not_found")

        def collect_events(cid: int, prefix_pos: tuple = ()):
            """Recursively collect events from chain and its sub-chains."""
            events = conn.execute("""
                SELECT e.id, e.title, e.first_seen, e.last_seen, e.article_count, ce.position, ce.note
                FROM chain_events ce
                JOIN events e ON e.id = ce.event_id
                WHERE ce.chain_id=? ORDER BY ce.position
            """, (cid,)).fetchall()

            results = []
            for evt in events:
                results.append({
                    'id': evt[0], 'title': evt[1], 'first_seen': evt[2], 'last_seen': evt[3],
                    'article_count': evt[4], 'position': evt[5], 'note': evt[6],
                    'sort_key': prefix_pos + (evt[5],), 'chain_id': cid,
                })

            sub_chains = conn.execute("""
                SELECT lc.id, lc.title, cr.position
                FROM chain_relations cr
                JOIN logic_chains lc ON lc.id = cr.child_chain_id
                WHERE cr.parent_chain_id=? ORDER BY cr.position
            """, (cid,)).fetchall()

            for sc in sub_chains:
                results.extend(collect_events(sc[0], prefix_pos + (sc[2],)))
            return results

        timeline = collect_events(chain_id)
        timeline.sort(key=lambda e: e['sort_key'])
        # Remove internal sort_key
        for e in timeline:
            del e['sort_key']

    return {'chain_id': chain_id, 'chain_title': chain[1], 'timeline': timeline, 'total_events': len(timeline)}

class UpdateChain(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None

@router.patch("/{chain_id}")
def update_chain(chain_id: int, body: UpdateChain):
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        updates = []
        params = []
        if body.title is not None:
            updates.append("title=?")
            params.append(body.title)
        if body.description is not None:
            updates.append("description=?")
            params.append(body.description)
        if updates:
            updates.append("updated_at=?")
            params.append(now)
            params.append(chain_id)
            conn.execute(f"UPDATE logic_chains SET {', '.join(updates)} WHERE id=?", params)
            conn.commit()
    return {'ok': True}

@router.delete("/{chain_id}")
def delete_chain(chain_id: int):
    db = get_db()
    with db._conn() as conn:
        conn.execute("DELETE FROM logic_chains WHERE id=?", (chain_id,))
        conn.commit()
    return {'ok': True}

class SpliceChains(BaseModel):
    child_chain_ids: list[int]

@router.post("/{chain_id}/splice")
def splice_chain(chain_id: int, body: SpliceChains):
    """Attach sub-chains to this parent chain."""
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        parent = conn.execute("SELECT id FROM logic_chains WHERE id=?", (chain_id,)).fetchone()
        if not parent:
            raise HTTPException(404, "parent_chain_not_found")
        for pos, child_id in enumerate(body.child_chain_ids):
            child = conn.execute("SELECT id FROM logic_chains WHERE id=?", (child_id,)).fetchone()
            if not child:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO chain_relations (parent_chain_id, child_chain_id, position)
                VALUES (?, ?, ?)
            """, (chain_id, child_id, pos))
        conn.execute("UPDATE logic_chains SET updated_at=? WHERE id=?", (now, chain_id))
        conn.commit()
    return {'ok': True}

class SplitChain(BaseModel):
    at_event_id: int
    new_title: str = ''

@router.post("/{chain_id}/split")
def split_chain(chain_id: int, body: SplitChain):
    """Split chain at a given event. Returns the new chain id."""
    db = get_db()
    now = datetime.now().isoformat(timespec='seconds')
    with db._conn() as conn:
        chain = conn.execute("SELECT title FROM logic_chains WHERE id=?", (chain_id,)).fetchone()
        if not chain:
            raise HTTPException(404, "chain_not_found")
        events = conn.execute(
            "SELECT id, event_id, position FROM chain_events WHERE chain_id=? ORDER BY position",
            (chain_id,)
        ).fetchall()

        split_index = None
        for idx, (eid, evt_id, pos) in enumerate(events):
            if evt_id == body.at_event_id:
                split_index = idx
                break
        if split_index is None:
            raise HTTPException(400, "event_not_in_chain")

        new_title = body.new_title or f"{chain[0]} (续)"
        # Create new chain
        cur = conn.execute(
            "INSERT INTO logic_chains (title, description, created_at, updated_at) VALUES (?, '', ?, ?)",
            (new_title, now, now)
        )
        new_id = cur.lastrowid
        # Move split events — use enumerate index to avoid position-gap collisions
        for idx, (eid, evt_id, pos) in enumerate(events):
            if idx >= split_index:
                conn.execute("UPDATE chain_events SET chain_id=?, position=? WHERE id=?",
                            (new_id, idx - split_index, eid))
        conn.execute("UPDATE logic_chains SET updated_at=? WHERE id=?", (now, chain_id))
        conn.commit()
    return {'ok': True, 'new_chain_id': new_id}

class ReorderChain(BaseModel):
    event_ids: list[int]

@router.post("/{chain_id}/reorder")
def reorder_chain(chain_id: int, body: ReorderChain):
    db = get_db()
    with db._conn() as conn:
        for pos, eid in enumerate(body.event_ids):
            conn.execute(
                "UPDATE chain_events SET position=? WHERE chain_id=? AND event_id=?",
                (pos, chain_id, eid)
            )
        conn.execute("UPDATE logic_chains SET updated_at=? WHERE id=?",
                    (datetime.now().isoformat(timespec='seconds'), chain_id))
        conn.commit()
    return {'ok': True}
