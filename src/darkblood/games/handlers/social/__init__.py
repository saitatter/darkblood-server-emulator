"""Social domain controller composed from friends, chat, party and guild mixins."""
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.social.chat import ChatHandlers
from darkblood.games.handlers.social.friends import FriendsHandlers
from darkblood.games.handlers.social.guild import GuildHandlers
from darkblood.games.handlers.social.party import PartyHandlers


class SocialHandlers(
    FriendsHandlers,
    ChatHandlers,
    PartyHandlers,
    GuildHandlers,
    BaseDomainService,
):
    """Friends, chat, party, teaching, guild and social notifications."""
