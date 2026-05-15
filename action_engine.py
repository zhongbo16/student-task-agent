import hashlib


def _clean_text(value):
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _compact_dict(values):
    return {
        key: value for key, value in (values or {}).items()
        if value not in (None, "", [])
    }


def _action_id(action_type, payload):
    raw = f"{action_type}:{repr(sorted((payload or {}).items()))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_title(value):
    return (_clean_text(value) or "").casefold()


def _resolve_task(suggestion, tasks):
    task_id = _clean_text(suggestion.get("task_id"))
    if task_id:
        for task in tasks:
            if str(task.get("id")) == task_id:
                return task, "matched by task id"
        return None, f"task id {task_id} was not found"

    title = _normalize_title(suggestion.get("title"))
    if not title:
        return None, "no task id or title was provided"

    matches = [
        task for task in tasks
        if _normalize_title(task.get("title")) == title
    ]
    if len(matches) == 1:
        return matches[0], "matched by exact title"
    if len(matches) > 1:
        return None, "multiple tasks have this exact title"
    return None, "no task matched this title"


def _make_action(action_type, label, payload, reason=None, status="ready"):
    action = {
        "id": _action_id(action_type, payload),
        "action_type": action_type,
        "label": label,
        "payload": payload,
        "reason": reason,
        "status": status,
    }
    return action


def build_confirmable_actions(proposal, command_date, tasks):
    """
    Convert a conversation proposal into explicit confirmable actions.

    This function is pure: it does not write to the database.
    """
    actions = []
    proposal = proposal or {}

    morning_updates = _compact_dict(proposal.get("morning_checkin_updates"))
    if morning_updates:
        actions.append(_make_action(
            "update_morning_checkin",
            "Update Morning Check-In",
            {
                "command_date": command_date,
                "updates": morning_updates,
            },
            reason="Conversation included today's availability, state, or constraints.",
        ))

    for commitment in proposal.get("personal_commitments") or []:
        title = _clean_text(commitment.get("title"))
        if not title:
            continue
        actions.append(_make_action(
            "create_personal_commitment",
            f"Add personal commitment: {title}",
            {
                "command_date": command_date,
                "commitment": commitment,
            },
            reason="Conversation mentioned a non-task commitment to plan around.",
        ))

    daily_review_update = _compact_dict(proposal.get("daily_review_update"))
    if daily_review_update:
        actions.append(_make_action(
            "update_daily_review",
            "Update Daily Review",
            {
                "command_date": command_date,
                "updates": daily_review_update,
            },
            reason="Conversation included information about what already happened.",
        ))

    for suggestion in proposal.get("task_status_suggestions") or []:
        task, resolution = _resolve_task(suggestion, tasks)
        suggested_status = _clean_text(suggestion.get("suggested_status"))
        title = _clean_text(suggestion.get("title")) or "task"
        payload = {
            "command_date": command_date,
            "suggestion": suggestion,
            "task_id": task.get("id") if task else None,
            "resolved_task_title": task.get("title") if task else None,
            "suggested_status": suggested_status,
        }
        status = "ready" if task and suggested_status else "needs_attention"
        label = (
            f"Change task status: {task.get('title')} -> {suggested_status}"
            if task else
            f"Review task status suggestion: {title} -> {suggested_status}"
        )
        actions.append(_make_action(
            "update_task_status",
            label,
            payload,
            reason=suggestion.get("reason") or resolution,
            status=status,
        ))

    for candidate in proposal.get("memory_candidates") or []:
        memory_key = _clean_text(candidate.get("memory_key"))
        memory_value = _clean_text(candidate.get("memory_value"))
        if not memory_key or not memory_value:
            continue
        actions.append(_make_action(
            "create_memory_candidate",
            f"Create memory candidate: {memory_key}",
            {
                "command_date": command_date,
                "candidate": candidate,
            },
            reason="Conversation included a possible durable preference or pattern.",
        ))

    return actions


def count_ready_actions(actions):
    return sum(1 for action in actions if action.get("status") == "ready")
