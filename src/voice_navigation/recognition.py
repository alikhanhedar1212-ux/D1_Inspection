"""Score complete commands without treating one weaker filler as the whole phrase."""
def confidence_score(words):
    if not words:
        return 0.0
    scores = [float(word.get('conf', 0)) for word in words]
    # Reject a very uncertain word even when other words are clear.
    if min(scores) < .50:
        return min(scores)
    return sum(scores) / len(scores)
