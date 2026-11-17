"""Monster kill (5063) grants the template's EXP through 5086."""
import os
import struct
import unittest
from pathlib import Path

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.hashing import jhash
from darkblood.games import session
from darkblood.games.game_data import client_dict

# Fields copied from the client's monster.lua entry 1npi01n0.
MONSTER_LUA = '\n'.join([
    'assert(DictMonster:LoadMonster({', '  {', '    DropCnt = 1,', '    Exp = 9.9,',
    '    ID = "1npi01n0",', '    Lv = 1,', '  }', '}), "DictMonster:LoadMonster")', ''])


class MonsterExpTest(ServerTestCase):
    def test_monster_dead_grants_exp(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        path = dict_dir / 'monster.lua'
        path.write_text(MONSTER_LUA, encoding='utf-8')
        client_dict.monsters.cache_clear()
        self.addCleanup(client_dict.monsters.cache_clear)
        self.addCleanup(path.unlink)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Hunter', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Live 5063: prefix + u32 template hash + u32 instance.
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, jhash('1npi01n0') & 0xFFFFFFFF, 0x03000fa2))
            _, exp = await client.expect_event(5086)
            total, gained = struct.unpack_from('<ii', exp)
            self.assertEqual(gained, 10)
            self.assertEqual(len(exp), 4 + 36)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['exp'], total)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
