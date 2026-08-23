import type {
  WallRect2D,
  Desk2D,
  Furniture2D,
  InteractivePOI,
  Doorway2D,
  EnvironmentalProp2D,
} from './types';

export const MAP_WIDTH = 1500;
export const MAP_HEIGHT = 950;
export const CELL_SIZE = 10; // 10px high-precision grid cells -> 150 x 95 = 14,250 cells

export const GRID_COLS = Math.ceil(MAP_WIDTH / CELL_SIZE);
export const GRID_ROWS = Math.ceil(MAP_HEIGHT / CELL_SIZE);

// 2D Collision Grid (0 = Walkable, 1 = Solid Obstacle)
const collisionGrid: Uint8Array = new Uint8Array(GRID_COLS * GRID_ROWS);

export interface ObstacleContext {
  walls: WallRect2D[];
  desks: Desk2D[];
  furniture: Furniture2D[];
  pois: InteractivePOI[];
  doorways?: Doorway2D[];
  environmentalProps?: EnvironmentalProp2D[];
}

/**
 * Priority Queue (Binary Min-Heap) implementation for fast O(log N) A* open set operations
 */
class BinaryMinHeap<T> {
  private items: T[] = [];
  private scoreFn: (item: T) => number;

  constructor(scoreFn: (item: T) => number) {
    this.scoreFn = scoreFn;
  }

  public push(item: T): void {
    this.items.push(item);
    this.bubbleUp(this.items.length - 1);
  }

  public pop(): T | undefined {
    if (this.items.length === 0) return undefined;
    const top = this.items[0];
    const bottom = this.items.pop();
    if (this.items.length > 0 && bottom !== undefined) {
      this.items[0] = bottom;
      this.sinkDown(0);
    }
    return top;
  }

  public size(): number {
    return this.items.length;
  }

  public clear(): void {
    this.items = [];
  }

  private bubbleUp(index: number): void {
    const item = this.items[index];
    if (!item) return;
    const itemScore = this.scoreFn(item);

    while (index > 0) {
      const parentIdx = Math.floor((index - 1) / 2);
      const parent = this.items[parentIdx];
      if (!parent || itemScore >= this.scoreFn(parent)) break;

      this.items[index] = parent;
      index = parentIdx;
    }
    this.items[index] = item;
  }

  private sinkDown(index: number): void {
    const length = this.items.length;
    const item = this.items[index];
    if (!item) return;
    const itemScore = this.scoreFn(item);

    while (true) {
      const leftChildIdx = 2 * index + 1;
      const rightChildIdx = 2 * index + 2;
      let swapIdx: number | null = null;
      let minScore = itemScore;

      if (leftChildIdx < length) {
        const leftChild = this.items[leftChildIdx];
        if (leftChild) {
          const leftScore = this.scoreFn(leftChild);
          if (leftScore < minScore) {
            minScore = leftScore;
            swapIdx = leftChildIdx;
          }
        }
      }

      if (rightChildIdx < length) {
        const rightChild = this.items[rightChildIdx];
        if (rightChild) {
          const rightScore = this.scoreFn(rightChild);
          if (rightScore < minScore) {
            swapIdx = rightChildIdx;
          }
        }
      }

      if (swapIdx === null) break;
      this.items[index] = this.items[swapIdx]!;
      index = swapIdx;
    }
    this.items[index] = item;
  }
}

/**
 * Checks if a world coordinate (x,y) is blocked by walls or obstacles
 */
export function isPointBlocked(x: number, y: number, buffer = 4): boolean {
  if (
    x < 16 + buffer ||
    x >= MAP_WIDTH - 16 - buffer ||
    y < 16 + buffer ||
    y >= MAP_HEIGHT - 16 - buffer
  ) {
    return true;
  }

  // Check center point
  const col = Math.floor(x / CELL_SIZE);
  const row = Math.floor(y / CELL_SIZE);
  if (col < 0 || col >= GRID_COLS || row < 0 || row >= GRID_ROWS) return true;
  if (collisionGrid[row * GRID_COLS + col] === 1) return true;

  // If buffer requested, check cardinal and diagonal perimeter offsets
  if (buffer > 0) {
    const minCol = Math.max(0, Math.floor((x - buffer) / CELL_SIZE));
    const maxCol = Math.min(GRID_COLS - 1, Math.floor((x + buffer) / CELL_SIZE));
    const minRow = Math.max(0, Math.floor((y - buffer) / CELL_SIZE));
    const maxRow = Math.min(GRID_ROWS - 1, Math.floor((y + buffer) / CELL_SIZE));

    for (let r = minRow; r <= maxRow; r++) {
      for (let c = minCol; c <= maxCol; c++) {
        if (collisionGrid[r * GRID_COLS + c] === 1) {
          const cx = (c + 0.5) * CELL_SIZE;
          const cy = (r + 0.5) * CELL_SIZE;
          if (Math.hypot(cx - x, cy - y) <= buffer) {
            return true;
          }
        }
      }
    }
  }

  return false;
}

/**
 * Initializes and bakes the collision grid from walls, desks, furniture, POIs, and doorways
 */
export function initCollisionGrid(ctx: ObstacleContext) {
  collisionGrid.fill(0);

  // 1. Mark outer perimeter borders as blocked (with 2-cell boundary)
  for (let c = 0; c < GRID_COLS; c++) {
    markCellBlocked(c, 0);
    markCellBlocked(c, 1);
    markCellBlocked(c, GRID_ROWS - 1);
    markCellBlocked(c, GRID_ROWS - 2);
  }
  for (let r = 0; r < GRID_ROWS; r++) {
    markCellBlocked(0, r);
    markCellBlocked(1, r);
    markCellBlocked(GRID_COLS - 1, r);
    markCellBlocked(GRID_COLS - 2, r);
  }

  // 2. Mark Walls as blocked
  ctx.walls.forEach((wall) => {
    markRectBlocked(wall.x, wall.y, wall.width, wall.height, 2);
  });

  // 3. Mark Desks as blocked
  ctx.desks.forEach((desk) => {
    markRectBlocked(desk.x, desk.y, desk.width, desk.height, 1);
  });

  // 4. Mark Large Furniture Obstacles
  ctx.furniture.forEach((f) => {
    if (f.type === 'table') {
      markRectBlocked(f.x + 2, f.y + 2, f.width - 4, f.height - 4, 1);
    } else if (f.type === 'server_rack') {
      markRectBlocked(f.x, f.y, f.width, f.height, 1);
    } else if (f.type === 'plant') {
      markRectBlocked(f.x + 3, f.y + 3, f.width - 6, f.height - 6, 0);
    } else if (f.type === 'sofa') {
      markRectBlocked(f.x + 2, f.y + 2, f.width - 4, f.height - 4, 1);
    }
  });

  // 5. Mark POI structures (Coffee, Arcade, Vending, Server, Zen Fountain)
  ctx.pois.forEach((poi) => {
    if (
      poi.type === 'coffee_machine' ||
      poi.type === 'arcade' ||
      poi.type === 'vending_machine' ||
      poi.type === 'fountain' ||
      poi.type === 'server_rack' ||
      poi.type === 'bookshelf'
    ) {
      markRectBlocked(poi.x, poi.y, poi.width, poi.height, 1);
    }
  });

  // 6. Mark Environmental Props (Filing Cabinets, Storage)
  if (ctx.environmentalProps) {
    ctx.environmentalProps.forEach((prop) => {
      if (prop.type === 'filing_cabinet' || prop.type === 'printer') {
        markRectBlocked(prop.x, prop.y, prop.width, prop.height, 1);
      }
    });
  }

  // 7. GUARANTEE ALL DOORWAYS & ENTRYWAYS ARE 100% UNBLOCKED & WIDE
  if (ctx.doorways) {
    ctx.doorways.forEach((door) => {
      unmarkRect(door.x - 8, door.y - 8, door.width + 16, door.height + 16);
    });
  }

  // 8. GUARANTEE ALL DESK SEATS & CHAIR APPROACH CHANNELS ARE WALKABLE
  ctx.desks.forEach((desk) => {
    unmarkPoint(desk.seatX, desk.seatY, 18);
    // Unmark clear approach channel towards the corridor based on desk orientation
    if (desk.facing === 'down') {
      unmarkPoint(desk.seatX, desk.seatY - 16, 16);
      unmarkPoint(desk.seatX, desk.seatY - 26, 14);
    } else if (desk.facing === 'up') {
      unmarkPoint(desk.seatX, desk.seatY + 16, 16);
      unmarkPoint(desk.seatX, desk.seatY + 26, 14);
    } else if (desk.facing === 'left') {
      unmarkPoint(desk.seatX + 16, desk.seatY, 16);
      unmarkPoint(desk.seatX + 26, desk.seatY, 14);
    } else if (desk.facing === 'right') {
      unmarkPoint(desk.seatX - 16, desk.seatY, 16);
      unmarkPoint(desk.seatX - 26, desk.seatY, 14);
    }
  });

  // 9. GUARANTEE ALL POI INTERACTION SPOTS ARE WALKABLE
  ctx.pois.forEach((poi) => {
    unmarkPoint(poi.interactX, poi.interactY, 20);
  });
}

function markRectBlocked(x: number, y: number, width: number, height: number, padding = 0) {
  const minCol = Math.max(0, Math.floor((x - padding) / CELL_SIZE));
  const maxCol = Math.min(GRID_COLS - 1, Math.floor((x + width + padding) / CELL_SIZE));
  const minRow = Math.max(0, Math.floor((y - padding) / CELL_SIZE));
  const maxRow = Math.min(GRID_ROWS - 1, Math.floor((y + height + padding) / CELL_SIZE));

  for (let r = minRow; r <= maxRow; r++) {
    for (let c = minCol; c <= maxCol; c++) {
      collisionGrid[r * GRID_COLS + c] = 1;
    }
  }
}

function markCellBlocked(c: number, r: number) {
  if (c >= 0 && c < GRID_COLS && r >= 0 && r < GRID_ROWS) {
    collisionGrid[r * GRID_COLS + c] = 1;
  }
}

function unmarkRect(x: number, y: number, width: number, height: number) {
  const minCol = Math.max(0, Math.floor(x / CELL_SIZE));
  const maxCol = Math.min(GRID_COLS - 1, Math.floor((x + width) / CELL_SIZE));
  const minRow = Math.max(0, Math.floor(y / CELL_SIZE));
  const maxRow = Math.min(GRID_ROWS - 1, Math.floor((y + height) / CELL_SIZE));

  for (let r = minRow; r <= maxRow; r++) {
    for (let c = minCol; c <= maxCol; c++) {
      collisionGrid[r * GRID_COLS + c] = 0;
    }
  }
}

function unmarkPoint(x: number, y: number, radius = 12) {
  const minCol = Math.max(0, Math.floor((x - radius) / CELL_SIZE));
  const maxCol = Math.min(GRID_COLS - 1, Math.floor((x + radius) / CELL_SIZE));
  const minRow = Math.max(0, Math.floor((y - radius) / CELL_SIZE));
  const maxRow = Math.min(GRID_ROWS - 1, Math.floor((y + radius) / CELL_SIZE));

  for (let r = minRow; r <= maxRow; r++) {
    for (let c = minCol; c <= maxCol; c++) {
      const cx = (c + 0.5) * CELL_SIZE;
      const cy = (r + 0.5) * CELL_SIZE;
      if (Math.hypot(cx - x, cy - y) <= radius) {
        collisionGrid[r * GRID_COLS + c] = 0;
      }
    }
  }
}

/**
 * Finds the nearest walkable cell if a target coordinate falls on a wall or obstacle
 */
export function findNearestWalkable(x: number, y: number): { x: number; y: number } {
  const clampedX = Math.max(30, Math.min(MAP_WIDTH - 30, x));
  const clampedY = Math.max(30, Math.min(MAP_HEIGHT - 30, y));

  const targetCol = Math.max(1, Math.min(GRID_COLS - 2, Math.floor(clampedX / CELL_SIZE)));
  const targetRow = Math.max(1, Math.min(GRID_ROWS - 2, Math.floor(clampedY / CELL_SIZE)));

  if (collisionGrid[targetRow * GRID_COLS + targetCol] === 0) {
    return { x: clampedX, y: clampedY };
  }

  // BFS outward concentric search to find nearest free cell with comfortable clearance
  for (let radius = 1; radius < 25; radius++) {
    for (let dr = -radius; dr <= radius; dr++) {
      for (let dc = -radius; dc <= radius; dc++) {
        if (Math.abs(dr) !== radius && Math.abs(dc) !== radius) continue;
        const nc = targetCol + dc;
        const nr = targetRow + dr;
        if (nc >= 2 && nc < GRID_COLS - 2 && nr >= 2 && nr < GRID_ROWS - 2) {
          if (collisionGrid[nr * GRID_COLS + nc] === 0) {
            return {
              x: (nc + 0.5) * CELL_SIZE,
              y: (nr + 0.5) * CELL_SIZE,
            };
          }
        }
      }
    }
  }

  return { x: clampedX, y: clampedY };
}

interface PathNode {
  c: number;
  r: number;
  g: number;
  h: number;
  f: number;
  parent: PathNode | null;
}

/**
 * Octile distance heuristic for 8-directional movement grid
 */
function octileDistance(dx: number, dy: number): number {
  const minD = Math.min(dx, dy);
  const maxD = Math.max(dx, dy);
  return 1.41421356 * minD + (maxD - minD);
}

/**
 * High-performance A* Pathfinding Algorithm navigating strictly around walls, desks, and obstacles
 */
export function findPath(
  startX: number,
  startY: number,
  endX: number,
  endY: number
): { x: number; y: number }[] {
  // Ensure start and end are in valid walkable territory
  const validStart = findNearestWalkable(startX, startY);
  const validEnd = findNearestWalkable(endX, endY);

  const startCol = Math.floor(validStart.x / CELL_SIZE);
  const startRow = Math.floor(validStart.y / CELL_SIZE);
  const endCol = Math.floor(validEnd.x / CELL_SIZE);
  const endRow = Math.floor(validEnd.y / CELL_SIZE);

  if (startCol === endCol && startRow === endRow) {
    return [{ x: validEnd.x, y: validEnd.y }];
  }

  // Fast Line of Sight Check (with clearance width): if straight corridor path is clear, return direct line
  if (hasLineOfSight(validStart.x, validStart.y, validEnd.x, validEnd.y, 8)) {
    return [{ x: validEnd.x, y: validEnd.y }];
  }

  const openHeap = new BinaryMinHeap<PathNode>((node) => node.f);
  const closedSet = new Uint8Array(GRID_COLS * GRID_ROWS);
  const gScore = new Float32Array(GRID_COLS * GRID_ROWS).fill(Infinity);

  const startH = octileDistance(Math.abs(endCol - startCol), Math.abs(endRow - startRow));
  const startNode: PathNode = {
    c: startCol,
    r: startRow,
    g: 0,
    h: startH,
    f: startH,
    parent: null,
  };

  openHeap.push(startNode);
  gScore[startRow * GRID_COLS + startCol] = 0;

  const neighbors = [
    { dc: 0, dr: -1, cost: 1.0 },
    { dc: 0, dr: 1, cost: 1.0 },
    { dc: -1, dr: 0, cost: 1.0 },
    { dc: 1, dr: 0, cost: 1.0 },
    // Diagonals (cost ~1.414)
    { dc: -1, dr: -1, cost: 1.4142 },
    { dc: 1, dr: -1, cost: 1.4142 },
    { dc: -1, dr: 1, cost: 1.4142 },
    { dc: 1, dr: 1, cost: 1.4142 },
  ];

  let iterations = 0;
  const maxIterations = 4000;

  while (openHeap.size() > 0 && iterations < maxIterations) {
    iterations++;

    const current = openHeap.pop();
    if (!current) break;

    // Check if reached destination
    if (Math.abs(current.c - endCol) <= 1 && Math.abs(current.r - endRow) <= 1) {
      // Reconstruct raw path
      const rawPath: { x: number; y: number }[] = [];
      let curr: PathNode | null = current;
      while (curr) {
        rawPath.push({
          x: (curr.c + 0.5) * CELL_SIZE,
          y: (curr.r + 0.5) * CELL_SIZE,
        });
        curr = curr.parent;
      }
      rawPath.reverse();
      rawPath.push({ x: validEnd.x, y: validEnd.y });

      // Smooth path with radius-aware line-of-sight raycasting
      return smoothPath(rawPath);
    }

    const currentIdx = current.r * GRID_COLS + current.c;
    closedSet[currentIdx] = 1;

    for (const n of neighbors) {
      const nc = current.c + n.dc;
      const nr = current.r + n.dr;

      if (nc < 0 || nc >= GRID_COLS || nr < 0 || nr >= GRID_ROWS) continue;

      const nIdx = nr * GRID_COLS + nc;
      if (closedSet[nIdx] === 1) continue;
      if (collisionGrid[nIdx] === 1) continue;

      // Prevent cutting diagonal corners through solid walls or desks
      if (n.dc !== 0 && n.dr !== 0) {
        const c1 = collisionGrid[current.r * GRID_COLS + nc];
        const c2 = collisionGrid[nr * GRID_COLS + current.c];
        if (c1 === 1 || c2 === 1) continue;
      }

      const tentativeG = current.g + n.cost;

      if (tentativeG < (gScore[nIdx] ?? Infinity)) {
        gScore[nIdx] = tentativeG;
        const h = octileDistance(Math.abs(endCol - nc), Math.abs(endRow - nr));
        const neighborNode: PathNode = {
          c: nc,
          r: nr,
          g: tentativeG,
          h,
          f: tentativeG + h * 1.02, // Slight tie-breaker multiplier for straight paths
          parent: current,
        };

        openHeap.push(neighborNode);
      }
    }
  }

  // Fallback: direct line to valid end point
  return [{ x: validEnd.x, y: validEnd.y }];
}

/**
 * Line of sight check between two points with clearance radius
 * Ensures that smoothed paths keep safe clearance from corners and obstacles
 */
export function hasLineOfSight(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  clearanceRadius = 7
): boolean {
  const dist = Math.hypot(x2 - x1, y2 - y1);
  const steps = Math.ceil(dist / (CELL_SIZE / 3)); // High-density step sampling
  if (steps === 0) return true;

  const dx = (x2 - x1) / steps;
  const dy = (y2 - y1) / steps;

  // Normal vector for width clearance checks
  const stepLen = Math.hypot(dx, dy);
  const nx = stepLen > 0 ? (-dy / stepLen) * clearanceRadius : 0;
  const ny = stepLen > 0 ? (dx / stepLen) * clearanceRadius : 0;

  for (let i = 0; i <= steps; i++) {
    const px = x1 + dx * i;
    const py = y1 + dy * i;

    // Check center ray
    const c = Math.floor(px / CELL_SIZE);
    const r = Math.floor(py / CELL_SIZE);
    if (c < 0 || c >= GRID_COLS || r < 0 || r >= GRID_ROWS) return false;
    if (collisionGrid[r * GRID_COLS + c] === 1) return false;

    // Check side bounds
    if (clearanceRadius > 0) {
      const cLeft = Math.floor((px + nx) / CELL_SIZE);
      const rLeft = Math.floor((py + ny) / CELL_SIZE);
      if (cLeft < 0 || cLeft >= GRID_COLS || rLeft < 0 || rLeft >= GRID_ROWS) return false;
      if (collisionGrid[rLeft * GRID_COLS + cLeft] === 1) return false;

      const cRight = Math.floor((px - nx) / CELL_SIZE);
      const rRight = Math.floor((py - ny) / CELL_SIZE);
      if (cRight < 0 || cRight >= GRID_COLS || rRight < 0 || rRight >= GRID_ROWS) return false;
      if (collisionGrid[rRight * GRID_COLS + cRight] === 1) return false;
    }
  }

  return true;
}

/**
 * Line of Sight Path Smoother / Funnel Algorithm with Corner Bezier Fillets
 * Eliminates jagged grid steps into smooth direct walking lines without cutting obstacle corners,
 * and adds organic curved corner fillets for smooth tweening through hallway turns.
 */
function smoothPath(rawPath: { x: number; y: number }[]): { x: number; y: number }[] {
  if (rawPath.length <= 2) return rawPath;

  const simplified: { x: number; y: number }[] = [];
  let currentIdx = 0;
  simplified.push(rawPath[0]!);

  while (currentIdx < rawPath.length - 1) {
    let furthestVisible = currentIdx + 1;
    for (let nextIdx = currentIdx + 2; nextIdx < rawPath.length; nextIdx++) {
      const pCurrent = rawPath[currentIdx]!;
      const pNext = rawPath[nextIdx]!;
      // Use 7px clearance when checking visibility to ensure ample room around corners
      if (hasLineOfSight(pCurrent.x, pCurrent.y, pNext.x, pNext.y, 7)) {
        furthestVisible = nextIdx;
      } else {
        break;
      }
    }
    simplified.push(rawPath[furthestVisible]!);
    currentIdx = furthestVisible;
  }

  if (simplified.length <= 2) return simplified;

  // Apply organic Bezier corner filleting to smoothed waypoints
  const curved: { x: number; y: number }[] = [simplified[0]!];

  for (let i = 1; i < simplified.length - 1; i++) {
    const pPrev = curved[curved.length - 1]!;
    const pCurr = simplified[i]!;
    const pNext = simplified[i + 1]!;

    const d1 = Math.hypot(pCurr.x - pPrev.x, pCurr.y - pPrev.y);
    const d2 = Math.hypot(pNext.x - pCurr.x, pNext.y - pCurr.y);

    const filletRadius = Math.min(10, d1 * 0.35, d2 * 0.35);

    if (filletRadius > 3) {
      const t1 = 1 - filletRadius / d1;
      const startCurve = {
        x: pPrev.x + (pCurr.x - pPrev.x) * t1,
        y: pPrev.y + (pCurr.y - pPrev.y) * t1,
      };

      const t2 = filletRadius / d2;
      const endCurve = {
        x: pCurr.x + (pNext.x - pCurr.x) * t2,
        y: pCurr.y + (pNext.y - pCurr.y) * t2,
      };

      const midCurve = {
        x: 0.25 * startCurve.x + 0.5 * pCurr.x + 0.25 * endCurve.x,
        y: 0.25 * startCurve.y + 0.5 * pCurr.y + 0.25 * endCurve.y,
      };

      if (
        !isPointBlocked(startCurve.x, startCurve.y, 3) &&
        !isPointBlocked(midCurve.x, midCurve.y, 3) &&
        !isPointBlocked(endCurve.x, endCurve.y, 3)
      ) {
        curved.push(startCurve);
        curved.push(midCurve);
        curved.push(endCurve);
        continue;
      }
    }

    curved.push(pCurr);
  }

  curved.push(simplified[simplified.length - 1]!);
  return curved;
}
