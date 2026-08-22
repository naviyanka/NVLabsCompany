import {
  MeshBuilder,
  PBRMaterial,
  StandardMaterial,
  Color3,
  Vector3,
  Animation,
  Scene,
  Mesh,
} from '@babylonjs/core';

export type DoorState = 'open' | 'closed' | 'locked';

/**
 * Interactive sliding door. Blocks navigation when closed.
 * Click to toggle open/close. Smooth animation.
 */
export class OfficeDoor {
  public readonly mesh: Mesh;
  public readonly frameMesh: Mesh;
  public state: DoorState = 'closed';

  private readonly _openOffset: Vector3;
  private readonly _closedPos: Vector3;
  private readonly _scene: Scene;

  constructor(
    id: string,
    position: Vector3,
    orientation: 'ns' | 'ew', // ns = door faces north/south, ew = faces east/west
    color: string,
    scene: Scene,
  ) {
    this._scene = scene;

    const doorWidth = 2.2;
    const doorHeight = 2.8;
    const doorThick = 0.08;

    const frameW = orientation === 'ns' ? doorWidth + 0.4 : doorThick + 0.3;
    const frameD = orientation === 'ns' ? doorThick + 0.3 : doorWidth + 0.4;

    // Door frame
    this.frameMesh = MeshBuilder.CreateBox(`${id}_frame`, {
      width: frameW,
      height: doorHeight + 0.2,
      depth: frameD,
    }, scene);
    this.frameMesh.position = position.clone();
    this.frameMesh.position.y = (doorHeight + 0.2) / 2;

    const frameMat = new PBRMaterial(`${id}_frameMat`, scene);
    frameMat.albedoColor = new Color3(0.08, 0.1, 0.18);
    frameMat.metallic = 0.7;
    frameMat.roughness = 0.3;
    this.frameMesh.material = frameMat;

    // Door panel (slides open)
    const panelW = orientation === 'ns' ? doorWidth : doorThick;
    const panelD = orientation === 'ns' ? doorThick : doorWidth;

    this.mesh = MeshBuilder.CreateBox(`${id}_panel`, {
      width: panelW,
      height: doorHeight - 0.2,
      depth: panelD,
    }, scene);
    this.mesh.position = position.clone();
    this.mesh.position.y = (doorHeight - 0.2) / 2;
    this._closedPos = this.mesh.position.clone();

    // Slide direction
    if (orientation === 'ns') {
      this._openOffset = new Vector3(doorWidth * 0.9, 0, 0);
    } else {
      this._openOffset = new Vector3(0, 0, doorWidth * 0.9);
    }

    // Door material — dark glass with accent color emissive strip
    const doorMat = new PBRMaterial(`${id}_doorMat`, scene);
    doorMat.albedoColor = new Color3(0.03, 0.04, 0.08);
    doorMat.metallic = 0.4;
    doorMat.roughness = 0.2;
    doorMat.alpha = 0.85;
    this.mesh.material = doorMat;

    // Emissive accent line on door
    const accentH = orientation === 'ns' ? doorWidth * 0.8 : doorThick + 0.1;
    const accentD = orientation === 'ns' ? doorThick + 0.1 : doorWidth * 0.8;
    const accent = MeshBuilder.CreateBox(`${id}_accent`, {
      width: accentH,
      height: 0.04,
      depth: accentD,
    }, scene);
    accent.position = position.clone();
    accent.position.y = doorHeight * 0.75;
    accent.parent = this.mesh;
    accent.position = new Vector3(0, doorHeight * 0.35, 0);

    const accentMat = new StandardMaterial(`${id}_accentMat`, scene);
    accentMat.emissiveColor = Color3.FromHexString(color).scale(0.8);
    accentMat.diffuseColor = Color3.FromHexString(color).scale(0.3);
    accent.material = accentMat;

    // Collision when closed
    this.mesh.checkCollisions = true;

    // Make clickable
    this.mesh.isPickable = true;
    this.frameMesh.isPickable = false;
  }

  open(): void {
    if (this.state === 'locked' || this.state === 'open') return;
    this.state = 'open';
    this.mesh.checkCollisions = false;
    this._animateTo(this._closedPos.add(this._openOffset));
  }

  close(): void {
    if (this.state === 'locked' || this.state === 'closed') return;
    this.state = 'closed';
    this.mesh.checkCollisions = true;
    this._animateTo(this._closedPos);
  }

  toggle(): void {
    if (this.state === 'open') this.close();
    else if (this.state === 'closed') this.open();
  }

  lock(): void {
    this.close();
    this.state = 'locked';
  }

  unlock(): void {
    if (this.state === 'locked') this.state = 'closed';
  }

  private _animateTo(target: Vector3): void {
    const anim = new Animation(
      'doorSlide',
      'position',
      30,
      Animation.ANIMATIONTYPE_VECTOR3,
      Animation.ANIMATIONLOOPMODE_CONSTANT,
    );
    anim.setKeys([
      { frame: 0, value: this.mesh.position.clone() },
      { frame: 15, value: target },
    ]);
    this.mesh.animations = [anim];
    this._scene.beginAnimation(this.mesh, 0, 15, false);
  }
}
