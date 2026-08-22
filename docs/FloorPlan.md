# NVLabs Mission Control — Babylon.js Interactive 3D Office Floor

## ROLE

You are an expert Babylon.js / TypeScript 3D environment engineer.

Build a production-quality, fully interactive 3D office environment for the NVLabs Mission Control application.

The attached reference image is the visual/layout reference for the office floor.

IMPORTANT:

The reference image must NOT be used as the actual floor texture, background, or a flat plane.

Reconstruct the entire office using real Babylon.js 3D geometry, materials, meshes, lighting, collisions, navigation, cameras, interaction logic, and reusable components.

The final result should look like a premium futuristic AI/technology operations office viewed from an elevated isometric/top-down camera.

---

# 1. PRIMARY OBJECTIVE

Create a complete interactive 3D office floor containing:

- Main Gate
- Reception
- Waiting Area
- Main Hallway
- Secondary Hallways
- Open Workspace
- Team Cabin 1
- Team Cabin 2
- Team Cabin 3
- Team Cabin 4
- Team Cabin 5
- Team Cabin 6
- Manager Cabin
- Meeting Hall
- Discussion Room 1
- Discussion Room 2
- Rest Area
- Server Room
- Storage Room
- Utility Room

The office should feel like one physically connected building.

Agents must be able to navigate through the building using valid paths.

Walls, furniture, doors and equipment must behave as physical obstacles.

---

# 2. TECHNOLOGY

Use:

- Babylon.js
- TypeScript
- React integration if the existing application uses React
- GLTF/GLB where appropriate
- Babylon GUI only where 3D-space UI is required
- HTML/React UI for application panels
- Babylon Navigation / Recast navigation where appropriate
- Babylon Pointer Events / picking
- Babylon Animation system
- Babylon PBR materials
- Babylon shadows
- Babylon post-processing
- Babylon Glow Layer where appropriate

Do NOT replace Babylon.js with Three.js.

Do NOT implement the office as a 2D canvas.

Do NOT use the reference image as a background.

---

# 3. REFERENCE IMAGE

Use the attached floor-plan image as the primary visual reference.

Preserve the following characteristics:

- Overall rectangular building
- Symmetrical futuristic office layout
- Dark navy/black environment
- Industrial sci-fi architecture
- Dark tiled floor
- Low-height interior walls
- Glass/metal architectural elements
- Warm architectural lights
- Cool blue environmental lighting
- Neon signage
- Modern desks
- Computer monitors
- Plants
- Server equipment
- Clean corridors
- Central meeting area
- Premium futuristic AI operations-center appearance

The reference image defines the visual direction and spatial arrangement.

However, all objects must be recreated as actual 3D objects.

---

# 4. WORLD COORDINATE SYSTEM

Use a consistent coordinate system.

```text
X = left / right
Y = vertical
Z = front / back

Use:

Y = 0

as the primary floor level.

Recommended overall building size:

Width  = approximately 120 world units
Depth  = approximately 80 world units

Do not hardcode arbitrary coordinates throughout the project.

Create a centralized floor-layout configuration.

Example:

interface RoomDefinition {
    id: string;
    name: string;
    x: number;
    z: number;
    width: number;
    depth: number;
    wallHeight: number;
    color: string;
    access: "public" | "team" | "manager" | "restricted";
}

All rooms should be generated from configuration.

5. FLOOR STRUCTURE

Create a large dark futuristic floor.

The floor should contain:

Large base mesh
Individual floor tile geometry
Subtle seams between tiles
Slight roughness variation
Very subtle reflective properties
Optional emissive edge strips
Realistic contact shadows

Do not make the grid excessively bright.

The floor should feel like dark polished industrial flooring.

Recommended tile size:

2 × 2 world units

The floor should remain visually clean.

6. OUTER BUILDING WALL

Create a complete outer perimeter.

The building should have:

Thick exterior walls
Rounded/chamfered corners
Dark metal panels
Glass sections
Blue edge lighting
Windows
Plants
Small architectural lights

The outer walls must be collision-enabled.

Agents must never be able to walk through them.

The camera should not clip through the outer walls during normal operation.

7. INTERIOR WALLS

Every room must have real physical walls.

Recommended:

Wall height: 2.5–3.5 units

Walls should use:

Dark metal
Dark glass
Metallic trim
Emissive strips
Subtle bevels
Architectural lighting

Avoid perfectly flat boring rectangles.

Use bevels/chamfers on important structural elements.

8. ROOM LAYOUT

Use the following conceptual layout.

┌────────────────────────────────────────────────────────────┐
│ TEAM 1 │ TEAM 2 │ UTILITY │ TEAM 3 │ TEAM 4              │
├────────┴────────┴─────────┴────────┴───────────────────────┤
│                                                            │
│ SERVER     │              MAIN HALLWAY        │ MANAGER    │
│ ROOM       │                                  │ CABIN      │
│            │         OPEN WORKSPACE            │            │
├────────────┤                                  ├────────────┤
│ STORAGE    │                                  │ REST AREA  │
│            ├──────────────┬───────────────────┤            │
│            │ DISCUSSION 1 │ DISCUSSION 2      │            │
├────────────┤              │                   ├────────────┤
│ TEAM 5     │    MEETING HALL                   │ TEAM 6     │
│            │                                   │            │
├────────────┴──────────────┬────────────────────┴────────────┤
│                           │                                  │
│       RECEPTION           │          WAITING AREA            │
│                           │                                  │
└───────────────────────────┴──────────────────────────────────┘
                         MAIN GATE

The exact proportions may be adjusted to create a believable physical building while preserving this structure.

9. MAIN GATE

Place the main entrance at the bottom-center of the building.

The entrance should contain:

Large futuristic door
Entrance frame
NVLabs-style illuminated emblem
Blue/white emissive lighting
Security scanner
Entry lights
Physical collision when closed

The entrance must connect directly to:

Main Gate
    ↓
Reception / Waiting Area
    ↓
Main Hallway
    ↓
Office

The gate must be a real interactive object.

10. RECEPTION

Reception should be positioned close to the main entrance.

Create:

Reception desk
Reception chair
Computer
Monitor
Small holographic display
Plants
Decorative lighting
NVLabs branding/signage

The reception desk must be a physical obstacle.

Agents should navigate around it.

11. WAITING AREA

Create a comfortable futuristic waiting area.

Include:

2–3 sofas
Coffee table
Decorative plants
Small digital display
Wall lighting
Ambient warm lighting

The area should feel different from the technical work areas.

12. MAIN HALLWAY

Create a clearly defined central hallway system.

The hallway should connect the major areas.

Hallways should be:

Wide enough for multiple agents
Visually distinct
Well illuminated
Free from unnecessary obstacles
Navigation-enabled

Recommended hallway width:

2.5–4 world units

Agents should use hallways as their preferred long-distance navigation routes.

13. TEAM CABINS 1–6

Each team cabin should be a proper enclosed office.

Every cabin should contain:

2–6 desks depending on available room
Matching office chairs
Monitors
Keyboard/mouse
Desk lighting
Plants
Small storage units
Wall display
Team cabin sign

Example workstation:

        MONITOR
           │
     ┌─────┴─────┐
     │   DESK    │
     └───────────┘
           │
         CHAIR

Desk and chair positions must be physically believable.

Do not place chairs inside desks.

Do not place monitors floating above desks.

Do not overlap furniture.

Maintain sufficient walking clearance around workstations.

14. WORKSTATION DESIGN

Create a reusable workstation prefab.

Example:

Workstation
├── Desk
├── Monitor
├── Monitor Stand
├── Keyboard
├── Mouse
├── Desk Light
├── Cable Details
├── Chair
└── Optional Plant

Create it once and instantiate it throughout the office.

Use instancing where appropriate.

Do not manually create completely independent geometry for every identical workstation.

15. OPEN WORKSPACE

The Open Workspace is the primary agent working area.

Create several workstation clusters.

Recommended layout:

┌─────────────────────────────────────┐
│                                     │
│   [D][D]       [D][D]       [D][D] │
│   [C][C]       [C][C]       [C][C] │
│                                     │
│   [D][D]       [D][D]       [D][D] │
│   [C][C]       [C][C]       [C][C] │
│                                     │
└─────────────────────────────────────┘

Where:

D = Desk
C = Chair

Create clear aisles between workstation groups.

Agents should be able to walk between workstation clusters.

Agents should NOT walk through desks or chairs.

16. MANAGER CABIN

Create a premium manager office.

Include:

Large manager desk
Manager chair
2 visitor chairs
Sofa
Coffee table
Large monitor
Wall display
Decorative plants
Storage cabinet
Premium lighting

The manager cabin should feel visually different from normal team cabins.

Access should be configurable.

Example:

access: "manager"

An agent without permission should not automatically enter the room.

17. MEETING HALL

Create the main central Meeting Hall.

It should be one of the visual focal points.

Include:

Large conference table
8–12 chairs
Central table display
Large wall screen
Holographic projector
Ceiling lights
Plants
Acoustic wall panels
Neon signage

The meeting hall must have multiple usable entry points where appropriate.

Agents should be able to enter and exit through those doors.

18. DISCUSSION ROOMS

Create two smaller discussion rooms.

Each should contain:

Round table
4–6 chairs
Wall monitor
Small plants
Ambient lighting
Interactive door

The rooms should be accessible from the main circulation system.

19. REST AREA

Create a dedicated employee/agent rest area.

Include:

Sofas
Lounge chairs
Small round table
Coffee machine
Plants
Ambient warm lighting
Wall display
Decorative elements

This should visually contrast with technical zones.

20. SERVER ROOM

Create a restricted server room.

Include:

Server racks
Network cabinets
Cable trays
Cooling equipment
Status LEDs
Network screens
Blue/cyan lighting

Server racks are physical obstacles.

Agents should only enter through the designated door.

Server room access should be permission-controlled.

21. STORAGE ROOM

Create a storage room.

Include:

Storage shelves
Boxes
Equipment cases
Workbench
Cabinets

Shelves and cabinets must be obstacles.

Do not create narrow gaps that agents cannot realistically navigate.

22. UTILITY ROOM

Create a utility room.

Include:

Electrical panels
Control panels
Utility cabinets
Maintenance equipment
Wall-mounted systems
Small workstation

Utility equipment should be physical obstacles.

23. DOORS

Every room must have an actual interactive door.

Create a reusable:

OfficeDoor

component.

The door should support:

open()
close()
toggle()
lock()
unlock()

Door states:

type DoorState =
    | "open"
    | "closed"
    | "locked";

When closed:

Door = obstacle

When open:

Door = traversable

When locked:

Door = inaccessible

Door opening should use smooth animation.

24. NAVIGATION SYSTEM

Implement real navigation.

Preferred:

Babylon.js Navigation / Recast

or another Babylon-compatible navigation solution.

Generate navigation based on actual scene geometry.

Do NOT use arbitrary teleportation between rooms.

Agents should physically walk through the office.

Navigation should account for:

Walls
Doors
Desks
Chairs
Tables
Cabinets
Server racks
Shelves
Plants
Other obstacles
25. NAVIGATION ZONES

Create logical navigation categories.

type NavigationArea =
    | "public"
    | "hallway"
    | "workspace"
    | "meeting"
    | "team"
    | "manager"
    | "restricted"
    | "rest";

Every room should declare its navigation/access policy.

Example:

{
    id: "server-room",
    access: "restricted",
    navigationArea: "restricted"
}
26. WHERE AGENTS CAN WALK

Agents can normally walk through:

Main Gate
Reception
Waiting Area
Main Hallway
Secondary Hallways
Open Workspace
Team Cabins
Meeting Hall
Discussion Rooms
Rest Area

Depending on permissions, agents may access:

Manager Cabin
Server Room
Utility Room
Storage Room
27. WHERE AGENTS CANNOT WALK

Agents must never walk through:

Exterior walls
Interior walls
Closed doors
Locked doors
Desks
Chairs
Tables
Server racks
Storage shelves
Cabinets
Utility equipment
Plants
Large decorative objects

Use actual collision/navigation geometry.

Do not rely only on visual meshes.

28. NAVIGATION CLEARANCE

Every walkable path must provide sufficient clearance.

Recommended:

Agent radius: 0.45–0.60 units
Agent height: 1.5–2.0 units

Maintain enough clearance around:

Desks
Chairs
Walls
Doors
Tables

Agents should not continuously collide with furniture.

29. AGENT MOVEMENT

Agents should have:

walkTo(position)
walkToRoom(roomId)
followPath(path)
stop()
pause()
resume()

Example:

agent.walkToRoom("meeting-hall");

The navigation system should calculate the actual path.

Do NOT hardcode:

agent.position = meetingHallPosition;

for normal movement.

That would bypass navigation.

30. AGENT PATHFINDING

Agents should choose sensible paths.

Example:

Team Cabin
    ↓
Door
    ↓
Hallway
    ↓
Meeting Hall

Not:

Team Cabin
    ↓
Through Wall
    ↓
Meeting Hall

The shortest valid navigation path should normally be preferred.

31. AGENT INTERACTION

Clicking an agent should:

Highlight the agent
Show selection ring
Smoothly focus the camera
Open the React agent information panel
Display agent status
Display current task
Display model
Display current room
Display progress

Example:

Agent Alpha


Status:
WORKING


Current Room:
Development / Open Workspace


Task:
Analyze target.com


Progress:
75%


Model:
Gemini


Current Activity:
Code analysis
32. ROOM INTERACTION

Clicking a room should:

Highlight the room
Highlight its boundary
Focus camera on the room
Display room information
Show agents inside
Show active tasks
Show capacity
Show room status

Example:

Development Zone


Agents:
6 / 8


Working:
4


Idle:
1


Review:
1
33. FURNITURE INTERACTION

Furniture may be selectable where useful.

Examples:

Click desk:

Desk 04
Assigned Agent:
Alpha
Status:
Occupied

Click monitor:

Monitor
Agent:
Alpha
Activity:
Code Analysis

Click server:

Server Rack 03
Status:
Healthy
Temperature:
42°C
34. VISUAL STYLE

Use a premium dark futuristic aesthetic.

Primary colors:

Background:
#020817


Dark Surface:
#07111F


Panel:
#0B1626


Blue:
#3B82F6


Purple:
#8B5CF6


Green:
#22C55E


Orange:
#F97316


Yellow:
#EAB308


Pink:
#EC4899


Cyan:
#06B6D4

Do not make every object neon.

Neon should be used as an accent.

35. LIGHTING

Use a layered lighting system.

Include:

Ambient/environment lighting
Soft directional light
Zone point lights
Local desk lights
Wall lights
Emissive materials
Subtle bloom
Shadows

Avoid extreme brightness.

The office should remain dark and cinematic.

36. ZONE COLORS

Use:

Team / Planning:
Purple


Development:
Green


Security:
Orange


Data:
Blue


Meeting:
Purple


Automation:
Blue


Research:
Yellow


Operations:
Blue


Support:
Pink

The new office layout can use neutral architectural colors while room signage and accent lighting communicate room identity.

37. SIGNAGE

Every major room should have a 3D sign.

Examples:

TEAM CABIN 01
TEAM CABIN 02
MANAGER CABIN
MEETING HALL
DISCUSSION ROOM
OPEN WORKSPACE
SERVER ROOM
REST AREA
RECEPTION

Use:

Dark transparent panel
Thin emissive border
Emissive text
Soft glow
Correct zone color

Signs should be physically positioned on walls.

Do not use HTML overlays for permanent room labels.

38. ENVIRONMENTAL DETAILS

Add realistic details:

Plants
Wall panels
Ceiling panels
Cable conduits
Monitor stands
Small storage units
Decorative lighting
Windows
Glass
Server equipment
Wall screens
Floor seams
Door frames
Architectural pillars

However, do not clutter the navigation paths.

Decorations should never accidentally block agent navigation.

39. AGENT VISUAL DESIGN

Create a reusable futuristic AI agent model.

The agent should visually resemble a small futuristic office robot.

Components:

Agent
├── Body
├── Head
├── Face / Screen
├── Status Light
├── Antenna
├── Shadow
├── Selection Ring
└── Nameplate

Use the assigned agent color as the emissive accent.

40. AGENT STATES

Support:

type AgentStatus =
    | "working"
    | "idle"
    | "review"
    | "offline"
    | "error"
    | "paused";

Visual behavior:

Working
Green glow
Typing animation
Monitor activity
Idle
Blue glow
Minimal animation
Review
Orange glow
Occasional pulse
Error
Red warning pulse
Offline
Dim/gray
Paused
Yellow/orange indicator
41. ANIMATION

Use subtle animation.

Animate:

Agents walking
Agent idle behavior
Monitor screens
Cursor activity
Server LEDs
Door opening
Door closing
Holograms
Neon lights
Small environmental effects

Avoid excessive animation.

The office should feel alive but professional.

42. CAMERA

Use a Babylon.js camera appropriate for an isometric/top-down office.

Recommended:

ArcRotateCamera

Initial position:

High angle
Slight perspective
Centered on office

Allow:

Zoom
Rotation
Pan
Smooth focus
Room focus
Agent focus

Controls:

Mouse wheel
    → Zoom


Left drag
    → Rotate


Middle/right drag
    → Pan


Double-click room
    → Focus room


Double-click agent
    → Focus agent

Do not allow the camera to go infinitely close to the floor.

Do not allow uncontrolled camera flipping.

43. RESPONSIVE DESIGN

The 3D office must work on:

1920×1080
1600×900
1440×900
1366×768
1280×720
Tablet
Mobile

Desktop:

Full office visible

Tablet:

Slightly closer camera
Reduced UI

Mobile:

Closer camera
Touch controls
Bottom-sheet object details

The 3D scene must resize automatically with the viewport.

44. PERFORMANCE

Optimize the scene for many agents.

Potential target:

50–200 agents

Use:

Thin instances
Instancing
AssetContainer
GLTF/GLB
LOD
Frustum culling
Shared materials
Shared textures
Simplified collision meshes
Efficient navigation meshes

Do NOT create unique geometry for every identical chair.

Create reusable assets.

45. COLLISION ARCHITECTURE

Separate:

Visual Mesh
Collision Mesh
Navigation Mesh

Example:

Desk
├── Visual Mesh
└── Collision Box


Chair
├── Visual Mesh
└── Simplified Collision


Server Rack
├── Visual Mesh
└── Collision Box

Do not use unnecessarily complex visual geometry for collision calculations.

46. SCENE ARCHITECTURE

Use a modular architecture.

Recommended:

src/
│
├── 3d/
│   ├── OfficeScene.ts
│   ├── OfficeRenderer.ts
│   ├── OfficeCamera.ts
│   ├── OfficeLighting.ts
│   ├── OfficeEnvironment.ts
│   │
│   ├── layout/
│   │   ├── floorLayout.ts
│   │   ├── roomDefinitions.ts
│   │   └── navigationDefinitions.ts
│   │
│   ├── rooms/
│   │   ├── Room.ts
│   │   ├── TeamCabin.ts
│   │   ├── ManagerCabin.ts
│   │   ├── MeetingHall.ts
│   │   ├── DiscussionRoom.ts
│   │   ├── RestArea.ts
│   │   ├── ServerRoom.ts
│   │   ├── StorageRoom.ts
│   │   └── UtilityRoom.ts
│   │
│   ├── furniture/
│   │   ├── Desk.ts
│   │   ├── Chair.ts
│   │   ├── Monitor.ts
│   │   ├── Sofa.ts
│   │   ├── ConferenceTable.ts
│   │   ├── ServerRack.ts
│   │   └── Plant.ts
│   │
│   ├── agents/
│   │   ├── Agent.ts
│   │   ├── AgentFactory.ts
│   │   ├── AgentAnimation.ts
│   │   ├── AgentMovement.ts
│   │   └── AgentManager.ts
│   │
│   ├── navigation/
│   │   ├── NavigationManager.ts
│   │   ├── NavigationAgent.ts
│   │   └── PathPlanner.ts
│   │
│   ├── doors/
│   │   ├── OfficeDoor.ts
│   │   └── DoorManager.ts
│   │
│   ├── interaction/
│   │   ├── InteractionManager.ts
│   │   ├── SelectionManager.ts
│   │   └── PickingManager.ts
│   │
│   └── effects/
│       ├── NeonEffect.ts
│       ├── GlowEffect.ts
│       └── EnvironmentEffects.ts
│
├── components/
│   ├── AgentPanel/
│   ├── RoomPanel/
│   ├── TaskPanel/
│   └── PipelinePanel/
│
└── data/
    ├── agents.ts
    ├── rooms.ts
    └── pipelines.ts

Adapt this structure to the existing project rather than blindly replacing the current architecture.

47. DATA-DRIVEN ROOMS

Example:

const rooms = [
    {
        id: "team-cabin-1",
        name: "Team Cabin 1",
        type: "team",
        access: "team",
        capacity: 6,
        color: "#8B5CF6"
    },


    {
        id: "manager-cabin",
        name: "Manager Cabin",
        type: "manager",
        access: "manager",
        capacity: 4,
        color: "#A78BFA"
    },


    {
        id: "server-room",
        name: "Server Room",
        type: "restricted",
        access: "restricted",
        capacity: 2,
        color: "#06B6D4"
    }
];

Do not hardcode room logic into the rendering code.

48. DATA-DRIVEN AGENTS

Use:

interface AgentDefinition {
    id: string;
    name: string;
    role: string;
    roomId: string;
    status: AgentStatus;
    model?: string;
    taskId?: string;
    color?: string;
}

Example:

{
    id: "alpha",
    name: "Alpha",
    role: "Planner",
    roomId: "team-cabin-1",
    status: "working",
    model: "Gemini"
}

The 3D office should react to this data.

49. REACT / BABYLON SEPARATION

Do not build the entire application inside Babylon.

Babylon should manage:

3D environment
Agents
Furniture
Camera
Lighting
Navigation
Animations
Picking
3D interactions

React should manage:

Agent information
Task information
Room information
Pipeline information
Settings
Controls
Application navigation

Expose a clean bridge.

Example:

office.selectAgent(agentId);


office.selectRoom(roomId);


office.focusAgent(agentId);


office.focusRoom(roomId);


office.updateAgent(agentId, state);


office.updateRoom(roomId, state);
50. REAL-TIME READY

Design the system so that real-time WebSocket updates can later control the office.

Example:

Backend
   ↓
WebSocket
   ↓
Agent State
   ↓
AgentManager
   ↓
Babylon Scene

If:

Alpha:
working

changes to:

Alpha:
idle

the 3D agent should automatically change appearance.

If:

Alpha:
room = "meeting-hall"

changes, the agent should navigate to the meeting hall.

51. PIPELINE VISUALIZATION

Create a system capable of visualizing active pipelines.

Example:

Planning
   ↓
Research
   ↓
Development
   ↓
QA & Security
   ↓
Operations

Use subtle animated energy/data paths between rooms.

The paths must NOT become physical navigation obstacles.

They are purely visual.

52. INTERACTION RULES

Implement:

Hover room
    → Room highlight


Click room
    → Select room


Double-click room
    → Focus camera


Hover agent
    → Agent highlight


Click agent
    → Select agent


Double-click agent
    → Focus camera


Click door
    → Open/close


Click desk
    → Desk information


Click server
    → Server information

Use smooth animations.

53. SELECTION EFFECT

Selected objects should receive:

Emissive outline
Soft glow
Selection ring
Slight visual elevation where appropriate

Do not dramatically alter the geometry.

54. ACCESS CONTROL

Create room permissions.

Example:

type AccessLevel =
    | "public"
    | "team"
    | "manager"
    | "restricted"
    | "admin";

Agents should have corresponding permissions.

Example:

agent.accessLevel = "team";

An agent should not enter:

restricted

areas without permission.

When access is denied:

Door remains closed
Agent receives navigation failure
UI may display "Access Denied"
Agent chooses another route
55. FAILURE HANDLING

Navigation must gracefully handle:

No path
Locked door
Blocked hallway
Temporary obstacle
Missing room
Invalid destination

Do not teleport the agent.

Instead:

Path unavailable
    ↓
Stop agent
    ↓
Show appropriate state
    ↓
Retry or choose alternate path
56. TEMPORARY OBSTACLES

Support dynamic obstacles.

For example:

Maintenance Cart
Temporary Equipment
Another Agent
Closed Door

Navigation should be capable of reacting.

Agents should recalculate paths when necessary.

57. AGENT-TO-AGENT AVOIDANCE

Agents should avoid walking directly through each other.

Implement reasonable local avoidance.

If full crowd simulation is excessive for the current project, implement a lightweight steering/avoidance layer.

Agents should:

Slow down
Slightly change direction
Wait when necessary

rather than overlap unnaturally.

58. VISUAL QUALITY

The final environment must look intentionally designed.

Avoid:

Primitive-looking placeholder geometry
Flat colors
Bright rainbow lighting
Empty rooms
Floating objects
Unrealistic proportions
Excessive UI
Excessive bloom
Cluttered corridors

The goal is:

Premium
Futuristic
Dark
Professional
Technological
Believable
Interactive
59. IMPLEMENTATION ORDER

Do NOT attempt to create everything randomly in one file.

Build in this order:

Phase 1

Create:

Babylon scene
Camera
Renderer
Environment
Floor
Outer walls

Verify rendering.

Phase 2

Create:

Rooms
Interior walls
Hallways
Doors

Verify physical layout.

Phase 3

Create:

Desks
Chairs
Monitors
Tables
Cabinets
Sofas
Plants
Server racks

Verify object placement.

Phase 4

Create:

Navigation mesh
Navigation areas
Collision system
Door traversal

Verify navigation.

Phase 5

Create:

Agent model
Agent factory
Agent animation
Agent movement

Verify agent paths.

Phase 6

Create:

Picking
Hover
Selection
Room interaction
Agent interaction

Verify interactions.

Phase 7

Create:

React integration
Agent panel
Room panel
Task panel

Verify UI synchronization.

Phase 8

Create:

Real-time state updates
Pipeline visualization
Dynamic agent movement

Verify live behavior.

Phase 9

Optimize:

Instancing
LOD
Materials
Textures
Navigation
Rendering
Memory
60. ACCEPTANCE CRITERIA

The implementation is NOT complete until all of these are true.

Visual
 Office resembles the provided reference
 All rooms exist
 Walls are correctly positioned
 Furniture is correctly positioned
 Lighting is cinematic
 Materials look premium
 Signage is readable
 No floating objects
 No overlapping objects
Navigation
 Main gate works
 Hallways are traversable
 Every accessible room has a valid path
 Doors work
 Closed doors block navigation
 Walls block navigation
 Furniture blocks navigation
 Restricted rooms enforce access
 Agents don't get stuck
 Agents don't teleport
 Agents avoid obstacles
 Agents avoid one another
Interaction
 Rooms are selectable
 Agents are selectable
 Doors are interactive
 Furniture can be selected where appropriate
 Camera can focus rooms
 Camera can focus agents
 Hover effects work
 Selection effects work
Responsive
 Desktop works
 Laptop works
 Tablet works
 Mobile works
 Camera adapts
 Touch controls work
Performance
 Shared assets are reused
 Identical furniture is instanced
 Collision geometry is simplified
 Navigation mesh is optimized
 Scene remains responsive with many agents
61. IMPORTANT DEVELOPMENT RULES

Do not:

Replace the existing application unnecessarily
Rewrite unrelated components
Remove existing Mission Control functionality
Use the reference image as a background
Hardcode agent positions
Teleport agents between rooms
Hardcode paths
Allow agents through walls
Create impossible furniture layouts
Put desks directly against doors
Block hallways with decorative objects
Put chairs inside walls
Use giant invisible collision boxes without reason

Do:

Reuse existing project architecture
Create reusable components
Keep data separate from rendering
Keep navigation separate from rendering
Keep UI separate from the 3D scene
Use TypeScript types
Add comments to complex systems
Keep the implementation extensible
Build incrementally
Test after each phase
62. FINAL REQUIREMENT

The final result should feel like a real interactive 3D office building rather than a 3D illustration.

A user should be able to:

Open the Mission Control application.
See the entire office from an elevated isometric view.
Rotate the camera.
Zoom in/out.
Pan around the building.
Click rooms.
Click agents.
Focus the camera on agents.
Watch agents walk between rooms.
See agents avoid desks and furniture.
See doors open and close.
See restricted areas enforce access.
See room lighting and signage.
See live agent states reflected visually.
Interact with the office on desktop and mobile.

The office should ultimately become the 3D physical representation of the NVLabs Mission Control system.

Do not stop at creating a visually attractive floor.

Build the actual underlying systems required to make the floor interactive, navigable, extensible, and ready for real-time agent orchestration.