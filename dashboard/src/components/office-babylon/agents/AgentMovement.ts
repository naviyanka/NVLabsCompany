import { Vector3, Scene, TransformNode } from '@babylonjs/core';

/**
 * Moves an agent along a waypoint path with smooth interpolation.
 * Agents walk at a constant speed, rotating to face movement direction.
 */
export class AgentMover {
  private _path: Vector3[] = [];
  private _currentIndex = 0;
  private _speed = 3; // units per second
  private _moving = false;
  private _node: TransformNode;
  private _onArrived?: () => void;

  constructor(node: TransformNode) {
    this._node = node;
  }

  get isMoving(): boolean {
    return this._moving;
  }

  /**
   * Start walking along a path of waypoints.
   */
  walkPath(path: Vector3[], speed?: number, onArrived?: () => void): void {
    if (path.length < 2) return;
    this._path = path;
    this._currentIndex = 0;
    this._speed = speed ?? 3;
    this._moving = true;
    this._onArrived = onArrived;
  }

  stop(): void {
    this._moving = false;
    this._path = [];
  }

  /**
   * Call every frame with deltaTime to advance movement.
   */
  update(deltaTime: number): void {
    if (!this._moving || this._path.length === 0) return;

    const target = this._path[this._currentIndex + 1];
    if (!target) {
      this._moving = false;
      this._onArrived?.();
      return;
    }

    const pos = this._node.position;
    const dir = target.subtract(pos);
    const dist = dir.length();

    if (dist < 0.1) {
      // Reached waypoint, advance to next
      this._currentIndex++;
      if (this._currentIndex >= this._path.length - 1) {
        this._node.position = target.clone();
        this._moving = false;
        this._onArrived?.();
      }
      return;
    }

    // Move toward target
    const step = this._speed * deltaTime;
    const move = dir.normalize().scale(Math.min(step, dist));
    this._node.position.addInPlace(move);

    // Face movement direction (Y rotation)
    if (dir.x !== 0 || dir.z !== 0) {
      this._node.rotation.y = Math.atan2(dir.x, dir.z);
    }
  }
}
