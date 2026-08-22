import { Vector3, Scene } from '@babylonjs/core';
import { rooms, type RoomDefinition } from '../layout/roomDefinitions';
import { OfficeDoor } from './OfficeDoor';

/**
 * Creates and manages all doors in the office.
 * Each room gets a door at each declared door position.
 */
export class DoorManager {
  public readonly doors: OfficeDoor[] = [];

  constructor(scene: Scene) {
    for (const room of rooms) {
      for (const dir of room.doors) {
        const door = this._createDoorForRoom(room, dir, scene);
        this.doors.push(door);
      }
    }

    // Main gate (larger, special)
    const mainGate = new OfficeDoor(
      'main-gate',
      new Vector3(0, 0, 20),
      'ns',
      '#3B82F6',
      scene,
    );
    this.doors.push(mainGate);
  }

  /** Toggle door on click by mesh name */
  handleClick(meshName: string): boolean {
    const door = this.doors.find(
      (d) => d.mesh.name === meshName || d.frameMesh.name === meshName,
    );
    if (door) {
      door.toggle();
      return true;
    }
    return false;
  }

  private _createDoorForRoom(room: RoomDefinition, dir: string, scene: Scene): OfficeDoor {
    const hw = room.width / 2;
    const hd = room.depth / 2;
    let pos: Vector3;
    let orientation: 'ns' | 'ew';

    switch (dir) {
      case 'north':
        pos = new Vector3(room.x, 0, room.z - hd);
        orientation = 'ns';
        break;
      case 'south':
        pos = new Vector3(room.x, 0, room.z + hd);
        orientation = 'ns';
        break;
      case 'west':
        pos = new Vector3(room.x - hw, 0, room.z);
        orientation = 'ew';
        break;
      case 'east':
        pos = new Vector3(room.x + hw, 0, room.z);
        orientation = 'ew';
        break;
      default:
        pos = new Vector3(room.x, 0, room.z + hd);
        orientation = 'ns';
    }

    return new OfficeDoor(`door_${room.id}_${dir}`, pos, orientation, room.color, scene);
  }
}
