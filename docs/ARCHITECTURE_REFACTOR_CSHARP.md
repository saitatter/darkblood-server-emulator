# Architecture Refactoring Guide: From Python Mixins to C# Composition

## 1. Context & Motivation

The Python server emulator initially used Python's multiple-inheritance mixin pattern:

```python
class GameSession(
    FrontendHandlers,
    SocialHandlers,
    MailHandlers,
    SquareHandlers,
    CommerceHandlers,
    InventoryHandlers,
    SkillHandlers,
    QuestHandlers,
    DungeonHandlers,
    ArenaHandlers,
    PetHandlers,
):
    ...
```

While convenient for prototyping in Python, this pattern creates major problems:
1. **Illegal in C#**: C# does **not** support multiple class inheritance. A class can implement multiple interfaces, but can only inherit from a single base class.
2. **Hidden State Coupling**: Mixin methods implicitly depend on `self.transport`, `self.current_char()`, `self.store()`, `self.active_char_id`, and `self.die_count` all being dynamically present on `self`.
3. **Difficult Unit Testing**: Testing a single opcode handler requires instantiating or mocking the entire mega-session.
4. **Namespace Collisions**: As more opcodes and helper methods are added across 11 domains, method names can collide.

---

## 2. Target Architecture: Composition & Packet Dispatcher

To provide a 1:1 blueprint for the upcoming C# port, we refactor the architecture into **Composition over Inheritance** using the **Domain Service & Dispatcher Pattern** (standard in modern MMORPG emulators like MHServerEmu / TrinityCore / AspNetCore).

```
                      +-------------------+
                      |   Client Socket   |
                      +---------+---------+
                                |
                                v
                      +-------------------+
                      |    GameSession    |
                      +----+---------+----+
                           |         |
          +----------------+         +----------------+
          |                                           |
          v                                           v
+--------------------+                     +--------------------+
|  PacketDispatcher  |                     |   Domain Services  |
+--------------------+                     +--------------------+
| 2036 -> Inventory  |                     | - InventoryService |
| 2050 -> Skills     |                     | - SkillService     |
| 2123 -> Mail       |                     | - DungeonService   |
| 5017 -> Dungeon    |                     | - ArenaService     |
| 5269 -> Arena      |                     | - CommerceService  |
+--------------------+                     +--------------------+
```

---

## 3. C# Implementation Blueprint

### A. The Packet Handler Interface
In C#, each packet handler or controller registers its handling delegates with the central dispatcher:

```csharp
namespace DarkBlood.Server.Network;

public delegate Task PacketHandlerDelegate(GameSession session, uint correlation, ReadOnlyMemory<byte> body);

public interface IPacketController
{
    void RegisterHandlers(PacketDispatcher dispatcher);
}
```

### B. The Packet Dispatcher
A fast, thread-safe array or dictionary mapping `ushort opcode` directly to delegates:

```csharp
namespace DarkBlood.Server.Network;

public class PacketDispatcher
{
    private readonly Dictionary<ushort, PacketHandlerDelegate> _handlers = new();

    public void Register(ushort opcode, PacketHandlerDelegate handler)
    {
        _handlers[opcode] = handler;
    }

    public void RegisterController(IPacketController controller)
    {
        controller.RegisterHandlers(this);
    }

    public async Task<bool> DispatchAsync(GameSession session, ushort opcode, uint correlation, ReadOnlyMemory<byte> body)
    {
        if (_handlers.TryGetValue(opcode, out var handler))
        {
            await handler(session, correlation, body);
            return true;
        }

        session.Transport.RecordUnhandled(opcode, correlation, body);
        return false;
    }
}
```

### C. Domain Services (Controllers)
Each domain is an independent service holding a typed reference to `GameSession`:

```csharp
namespace DarkBlood.Server.Games.Inventory;

public class InventoryService : IPacketController
{
    private readonly GameSession _session;

    public InventoryService(GameSession session)
    {
        _session = session;
    }

    public void RegisterHandlers(PacketDispatcher dispatcher)
    {
        dispatcher.Register(2026, HandleOpenBagAsync);
        dispatcher.Register(2036, HandleDragItemAsync);
        dispatcher.Register(2038, HandleUseItemAsync);
        dispatcher.Register(2042, HandleEquipItemAsync);
        dispatcher.Register(2228, HandleDepotSaveArAsync);
        dispatcher.Register(2230, HandleDepotLoadArAsync);
    }

    public async Task HandleDragItemAsync(GameSession session, uint correlation, ReadOnlyMemory<byte> body)
    {
        var req = DragItemReq.Decode(body.Span);
        var charRecord = session.CurrentCharacter;
        // Business logic...
        await session.SendEventAsync(2037, new DragItemAck { Result = 0, Items = updatedItems });
    }
}
```

### D. GameSession (Pure Composition)
`GameSession` does **not** inherit any domain classes; it instantiates them via composition:

```csharp
namespace DarkBlood.Server.Games;

public class GameSession
{
    public ITransport Transport { get; }
    public CharacterStore Store { get; }
    public string Account { get; set; } = "OfflinePlayer";
    public long? ActiveCharId { get; set; }

    // Domain Services via Composition
    public InventoryService Inventory { get; }
    public SkillService Skills { get; }
    public DungeonService Dungeon { get; }
    public ArenaService Arena { get; }
    public MailService Mail { get; }
    public CommerceService Commerce { get; }

    public PacketDispatcher Dispatcher { get; }

    public GameSession(ITransport transport, CharacterStore store, PacketDispatcher dispatcher)
    {
        Transport = transport;
        Store = store;
        Dispatcher = dispatcher;

        // Instantiate domain controllers passing 'this'
        Inventory = new InventoryService(this);
        Skills = new SkillService(this);
        Dungeon = new DungeonService(this);
        Arena = new ArenaService(this);
        Mail = new MailService(this);
        Commerce = new CommerceService(this);

        // Register domain handlers
        Dispatcher.RegisterController(Inventory);
        Dispatcher.RegisterController(Skills);
        Dispatcher.RegisterController(Dungeon);
        Dispatcher.RegisterController(Arena);
        Dispatcher.RegisterController(Mail);
        Dispatcher.RegisterController(Commerce);
    }

    public async Task OnUserMessageAsync(ReadOnlyMemory<byte> payload)
    {
        var (opcode, correlation, body) = JSer.ParseEvent(payload.Span);
        await Dispatcher.DispatchAsync(this, opcode, correlation, body);
    }
}
```

---

## 4. Benefits of this Refactoring

1. **Zero Multiple Inheritance**: 100% compliant with C#, Java, Go, Rust, or any strongly typed OOP language.
2. **Explicit Dependency Flow**: Handlers explicitly receive or access `session`, eliminating hidden attribute leaks.
3. **Modular Testing**: Individual domain services can be unit-tested in isolation by providing a mock `GameSession`.
4. **Seamless Transition**: In Python, `PacketDispatcher` and `BaseDomainService` provide dynamic dispatch while preserving full backward compatibility with existing tests.
