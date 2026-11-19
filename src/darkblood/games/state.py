"""Process-wide game state shared by the game and relay connections."""

# Last character selected by any game connection (2006). Only a fallback:
# each GameSession keeps its own selection (GameSession.char_id) so two
# clients can play different characters at the same time.
selected_character = {'id': 0}
