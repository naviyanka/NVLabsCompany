# Office 3D Floor — Micro-Phase Implementation Plan

> Based on `docs/FloorPlan.md` spec + reference image. Migrating from React Three Fiber to Babylon.js.
> Each phase is independently testable. Complete phases in order.

---

## Phase 0: Foundation & Migration Setup

### 0.1 — Install Babylon.js dependencies
- `@babylonjs/core`, `@babylonjs/loaders`, `@babylonjs/gui`, `@babylonjs/materials`
- Remove `@react-three/fiber`, `@react-three/drei`, `three`, `@types/three` from dashboard deps
- **Acceptance:** `npm run build` succeeds with Babylon imports

### 0.2 — Create BabylonCanvas React wrapper
- File: `dashboard/src/components/office-babylon/BabylonCanvas.tsx`
- React component that creates a `<canvas>`, initializes Babylon Engine + Scene
- Exposes scene ref for child components
- Handles resize, dispose on unmount
- **Acceptance:** Black canvas renders at `/office` route

### 0.3 — Create scene entry point
- File: `dashboard/src/components/office-babylon/OfficeScene.ts`
- Creates Scene, sets background `#020817`
- Exports `initOfficeScene(engine, canvas)` function
- **Acceptance:** Dark blue background visible

### 0.4 — Camera setup
- File: `dashboard/src/components/office-babylon/OfficeCamera.ts`
- ArcRotateCamera, initial position: high isometric angle
- Controls: scroll=zoom, left-drag=rotate, right-drag=pan
- Limits: min/max radius, min/max beta (no floor clip, no flip)
- Double-click focus support (stub)
- **Acceptance:** Can orbit, zoom, pan around empty scene

---

## Phase 1: Floor & Outer Shell

### 1.1 — Floor mesh
- File: `dashboard/src/components/office-babylon/environment/Floor.ts`
- Large plane (120×80 units), dark polished material
- Tile grid via texture or subtle geometry (2×2 unit tiles)
- PBR material: dark, slight metalness, low roughness
- **Acceptance:** Dark tiled floor visible from camera

### 1.2 — Outer walls
- File: `dashboard/src/components/office-babylon/environment/OuterWalls.ts`
- Perimeter walls (120×80), height 3.5 units
- Dark metal PBR material
- Blue emissive edge strips at base/top
- Glass window sections (transparent material)
- Collision enabled on all walls
- **Acceptance:** Complete building perimeter, camera can't clip through

### 1.3 — Ambient lighting
- File: `dashboard/src/components/office-babylon/environment/Lighting.ts`
- Ambient: dim blue-white (intensity 0.3)
- Directional: from above-right (intensity 0.4)
- Hemisphere: ground=#020817, sky=#1a2040
- **Acceptance:** Geometry visible with cinematic dark feel

---

## Phase 2: Room Layout & Interior Walls

### 2.1 — Room definitions config
- File: `dashboard/src/components/office-babylon/layout/roomDefinitions.ts`
- Interface: `RoomDefinition { id, name, type, x, z, width, depth, wallHeight, color, access }`
- All 16 rooms defined per floor plan ASCII layout
- **Acceptance:** TypeScript compiles, rooms are importable

### 2.2 — Interior wall generator
- File: `dashboard/src/components/office-babylon/layout/WallBuilder.ts`
- Takes room definitions, generates wall meshes between rooms
- Wall material: dark metal + metallic trim + emissive accent strip
- Collision enabled
- Doorway gaps (position defined per room)
- **Acceptance:** All rooms enclosed, hallways open

### 2.3 — Hallway system
- Main hallway: horizontal center corridor (width 4 units)
- Secondary hallways connecting to rooms
- Floor marking (subtle emissive strips along hallway edges)
- **Acceptance:** Clear navigable corridors between all rooms

### 2.4 — Room floor coloring
- Each room gets a tinted floor section (subtle, not garish)
- Material per room type (slightly different roughness/tint)
- **Acceptance:** Rooms visually distinguishable from hallways

---

## Phase 3: Doors

### 3.1 — Door prefab
- File: `dashboard/src/components/office-babylon/doors/OfficeDoor.ts`
- Class: `OfficeDoor` with `open()`, `close()`, `toggle()`, `lock()`, `unlock()`
- Animated slide/swing open (Babylon animation system)
- States: open | closed | locked
- Collision: blocks when closed, passable when open
- **Acceptance:** Door opens/closes on click with animation

### 3.2 — Door placement
- File: `dashboard/src/components/office-babylon/doors/DoorManager.ts`
- Places doors at every room entrance per layout
- Main gate: large double door at bottom-center
- **Acceptance:** Every room has a functional door

---

## Phase 4: Furniture Prefabs

### 4.1 — Workstation prefab
- File: `dashboard/src/components/office-babylon/furniture/Workstation.ts`
- Desk + monitor + monitor stand + keyboard + mouse + chair + desk light
- Single createWorkstation() function, returns parent TransformNode
- Uses instancing for repeated placement
- **Acceptance:** One workstation visible with all components

### 4.2 — Conference table prefab
- File: `dashboard/src/components/office-babylon/furniture/ConferenceTable.ts`
- Large table + N chairs arranged around it
- **Acceptance:** Meeting table with chairs renders

### 4.3 — Sofa, coffee table, plants
- File: `dashboard/src/components/office-babylon/furniture/Lounge.ts`
- Sofa (box + cushions), coffee table, potted plant
- **Acceptance:** Rest area furniture renders

### 4.4 — Server rack prefab
- File: `dashboard/src/components/office-babylon/furniture/ServerRack.ts`
- Tall cabinet, status LEDs (emissive small boxes), cable tray
- **Acceptance:** Server rack with blinking LEDs

### 4.5 — Storage shelves, cabinets
- File: `dashboard/src/components/office-babylon/furniture/Storage.ts`
- Shelving unit, filing cabinet, boxes
- **Acceptance:** Storage room furnishable

---

## Phase 5: Room Population

### 5.1 — Team Cabins 1–6
- 6 desks, 6 chairs, 6 monitors, 1 whiteboard, 2 plants per cabin
- Desks arranged in pairs facing each other
- **Acceptance:** All 6 team cabins furnished

### 5.2 — Open Workspace
- 16 desks (4×4 layout), 16 chairs, 16 monitors, 8 plants
- Clear aisles between clusters
- **Acceptance:** Open workspace fully populated

### 5.3 — Manager Cabin
- Manager desk, chair, 2 visitor chairs, sofa, cabinet, large monitor, plants
- Premium lighting (warmer)
- **Acceptance:** Manager office visually distinct

### 5.4 — Meeting Hall
- 1 large table, 8 chairs, 1 wall screen, 2 plants
- Central ceiling light
- **Acceptance:** Meeting hall functional

### 5.5 — Discussion Rooms 1 & 2
- Round table, 6 chairs, wall monitor, plant per room
- **Acceptance:** Both discussion rooms furnished

### 5.6 — Server Room
- 3 server racks, 1 workstation desk, 1 chair, 1 monitor
- Cyan/blue lighting
- **Acceptance:** Server room with racks and LEDs

### 5.7 — Rest Area
- 2 sofas, round table, 2 vending machines (box shapes), 2 plants
- Warm amber lighting
- **Acceptance:** Rest area cozy and distinct

### 5.8 — Reception & Waiting Area
- Reception: desk, chair, monitor, 2 plants
- Waiting: 2 sofas, coffee table, 2 plants
- NVLabs signage
- **Acceptance:** Entrance area complete

### 5.9 — Storage & Utility rooms
- Storage: shelves, boxes, workbench
- Utility: electrical panels (flat boxes on wall), cabinets, workstation
- **Acceptance:** Both utility rooms furnished

---

## Phase 6: Signage & Environmental Detail

### 6.1 — Room signs
- 3D text or textured plane per room
- Dark panel + emissive text in room color
- Mounted above/beside door
- **Acceptance:** Every room labeled

### 6.2 — Main gate emblem
- NVLabs logo/text, illuminated
- Security scanner mesh beside gate
- **Acceptance:** Entrance looks premium

### 6.3 — Environmental polish
- Ceiling panels (flat dark boxes above rooms)
- Cable conduits along walls (thin cylinders)
- Small wall lights (emissive boxes every N units along hallways)
- Window sections in outer wall (glass material)
- **Acceptance:** Environment feels detailed, not empty

---

## Phase 7: Navigation System

### 7.1 — Navigation mesh generation
- File: `dashboard/src/components/office-babylon/navigation/NavigationManager.ts`
- Use Babylon Recast plugin or manual nav mesh
- Bake from room geometry (exclude walls, furniture, closed doors)
- **Acceptance:** Nav mesh covers all walkable areas

### 7.2 — Agent pathfinding
- File: `dashboard/src/components/office-babylon/navigation/PathPlanner.ts`
- `findPath(from, to)` returns waypoint array
- Respects walls, furniture, closed doors
- Uses hallways for long routes
- **Acceptance:** Path from any room to any room is valid

### 7.3 — Door-aware navigation
- Closed door = blocked segment
- Open door = passable
- Locked + insufficient access = path fails gracefully
- **Acceptance:** Agent can't path through closed doors

---

## Phase 8: Agent System

### 8.1 — Agent visual model
- File: `dashboard/src/components/office-babylon/agents/AgentModel.ts`
- Small robot: body (capsule), head (sphere), status light ring, nameplate
- Color from agent data, status glow (green/yellow/orange/gray/red)
- **Acceptance:** Agent renders at a position

### 8.2 — Agent factory & manager
- File: `dashboard/src/components/office-babylon/agents/AgentManager.ts`
- Create agents from data array
- Place at assigned desk/room
- Track all active agents
- **Acceptance:** Multiple agents visible at their desks

### 8.3 — Agent movement
- `walkTo(position)`, `walkToRoom(roomId)`
- Follows nav mesh path
- Smooth interpolation along waypoints
- Idle animation when stationary
- **Acceptance:** Agent walks between rooms through hallways

### 8.4 — Agent avoidance
- Lightweight: agents don't overlap
- Slow down near other agents
- Brief wait if path blocked by another agent
- **Acceptance:** Two agents don't walk through each other

---

## Phase 9: Interaction & Picking

### 9.1 — Picking manager
- File: `dashboard/src/components/office-babylon/interaction/PickingManager.ts`
- Pointer hover → highlight mesh
- Click → select (emissive outline + glow)
- Differentiate: room click, agent click, furniture click, door click
- **Acceptance:** Hover shows highlight, click shows selection

### 9.2 — Camera focus
- Double-click room → smooth camera animate to room center
- Double-click agent → smooth camera follow agent
- Click background → deselect
- **Acceptance:** Focus animations work smoothly

### 9.3 — Door interaction
- Click door → toggle open/close
- Visual: door slides/swings with animation
- Nav mesh updates on door state change
- **Acceptance:** Doors open/close on click

---

## Phase 10: React Integration & UI Panels

### 10.1 — Bridge API
- File: `dashboard/src/components/office-babylon/OfficeBridge.ts`
- Exposes: `selectAgent(id)`, `selectRoom(id)`, `focusAgent(id)`, `focusRoom(id)`, `updateAgent(id, state)`
- Events: `onAgentSelected`, `onRoomSelected`, `onDoorToggled`
- **Acceptance:** React can drive 3D scene, 3D events reach React

### 10.2 — Agent info panel
- Shows on agent select: name, role, status, room, task, progress, model
- React component overlays on right side
- **Acceptance:** Click agent → panel appears with data

### 10.3 — Room info panel
- Shows on room select: name, capacity, agents inside, active tasks
- **Acceptance:** Click room → panel shows room data

### 10.4 — Stats bar (top)
- Total agents, active/idle/review/offline counts
- Already exists — wire to Babylon selection events
- **Acceptance:** Stats update from scene state

---

## Phase 11: Real-Time & Polish

### 11.1 — WebSocket-ready state updates
- `AgentManager.updateAgent(id, newState)` changes visual state live
- Status change → color/glow change
- Room change → agent navigates to new room
- **Acceptance:** Programmatic state change reflects visually

### 11.2 — Post-processing
- Glow layer for emissive elements
- Subtle bloom (low threshold)
- FXAA
- **Acceptance:** Scene looks polished with post-processing

### 11.3 — Performance optimization
- Thin instances for identical furniture
- Simplified collision meshes
- LOD for distant objects (if needed)
- Frustum culling verified
- **Acceptance:** Smooth 60fps with 50+ agents

### 11.4 — Responsive / mobile
- Canvas resizes with viewport
- Touch controls: one-finger=rotate, two-finger=zoom/pan
- Mobile: closer default camera, bottom-sheet panels
- **Acceptance:** Works on tablet and mobile

---

## Summary

| Phase | Focus | Files Created |
|-------|-------|---------------|
| 0 | Foundation, Babylon setup, camera | 4 |
| 1 | Floor, outer walls, lighting | 3 |
| 2 | Room layout, interior walls, hallways | 3 |
| 3 | Doors (prefab + placement) | 2 |
| 4 | Furniture prefabs (5 types) | 5 |
| 5 | Room population (all 16 rooms) | 9 sub-tasks |
| 6 | Signage, emblem, environmental detail | 3 |
| 7 | Navigation mesh + pathfinding | 3 |
| 8 | Agent model, factory, movement, avoidance | 4 |
| 9 | Picking, camera focus, door interaction | 3 |
| 10 | React bridge, UI panels | 4 |
| 11 | Real-time, post-processing, perf, mobile | 4 |

**Total: 12 phases, ~47 sub-tasks**

Each phase builds on the previous. Test after each sub-task before moving on.
