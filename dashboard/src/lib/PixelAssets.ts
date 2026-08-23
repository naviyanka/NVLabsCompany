import { Container, Graphics, Texture, CanvasSource, Sprite } from 'pixi.js';
import { useState, useEffect } from 'react';
import {
  draw3DDesk,
  drawDeskShadow,
  draw3DChair,
  drawChairShadow,
  drawConferenceTable,
  drawRoundCafeTable,
  drawEspressoMachine,
  drawArcadeCabinet,
  drawWaterCooler,
  drawVendingMachine,
  drawServerRack3D,
  drawPlushSofa,
  drawCoffeeTable,
  drawZenBench,
  drawZenFountain,
  drawPottedPlant,
  drawWhiteboard,
  drawBookshelf,
  drawEnvironmentalProp,
} from '@/components/office2d/furnitureRenderer';
import { OFFICE_2D_LAYOUT } from '@/components/office2d/office2DMap';
import type {
  Desk2D,
  EnvironmentalProp2D,
  Furniture2D,
  InteractivePOI,
} from '@/components/office2d/types';

/**
 * ============================================================================
 * PIXEL ASSETS & PIXIJS ASSET LOADER MODULE (src/lib/PixelAssets.ts)
 * ============================================================================
 * 
 * High-performance 2.5D / 3/4 isometric asset management, preloading, and
 * texture caching system for PixiJS. Pre-renders and caches all dimensional
 * furniture, datacenter compute racks, storage cabinets, appliances, and 
 * architectural environment sprites before the Office canvas render loop begins.
 */

// ============================================================================
// 1. TYPE DEFINITIONS & INTERFACES
// ============================================================================

export type LayerType = 'shadow' | 'base' | 'frontFace' | 'topSurface' | 'sideFace' | 'details';

export interface CollisionBox {
  x: number;
  y: number;
  width: number;
  height: number;
  zElevation?: number;
}

export interface ContactShadowSpec {
  offsetX: number;
  offsetY: number;
  width: number;
  height: number;
  opacity: number;
  shape: 'ellipse' | 'roundedRect' | 'rect';
  cornerRadius?: number;
}

export interface AssetDimensions {
  width: number;
  height: number;
  visualHeight: number;
  depth: number;
}

export interface RenderContext2D {
  now: number;
  scale?: number;
  highlighted?: boolean;
}

export interface ColorPalette {
  top: number | string;
  bevel: number | string;
  front: number | string;
  side: number | string;
  trim: number | string;
  shadow: number | string;
  accent?: number | string;
}

// ============================================================================
// 2. PALETTE DICTIONARY
// ============================================================================

export const ASSET_PALETTES = {
  carbon: {
    top: 0x1c1e24,
    bevel: 0x2e323d,
    front: 0x131418,
    side: 0x0d0e11,
    trim: 0x3b404e,
    shadow: 0x07080a,
    accent: 0x38bdf8,
  },
  darkMahogany: {
    top: 0x451a13,
    bevel: 0x61281e,
    front: 0x2e0f0a,
    side: 0x1f0906,
    trim: 0x783528,
    shadow: 0x100403,
    accent: 0xca8a04,
  },
  walnut: {
    top: 0x38281c,
    bevel: 0x4f3b2c,
    front: 0x261b12,
    side: 0x1a120b,
    trim: 0x694f3a,
    shadow: 0x0e0905,
    accent: 0xf59e0b,
  },
  oak: {
    top: 0x4d3d2c,
    bevel: 0x6b5740,
    front: 0x362a1e,
    side: 0x241c13,
    trim: 0x856d51,
    shadow: 0x140f09,
    accent: 0x10b981,
  },
  steelChassis: {
    top: 0x1e2029,
    bevel: 0x2b2e3b,
    front: 0x14161d,
    side: 0x0c0d12,
    trim: 0x3f4357,
    shadow: 0x06070a,
    accent: 0x06b6d4,
  },
  serverPlinth: {
    top: 0x1e222d,
    bevel: 0x333a4c,
    front: 0x0b0e14,
    side: 0x0a0c10,
    trim: 0x475569,
    shadow: 0x040507,
    accent: 0x10b981,
  },
  executiveLeather: {
    top: 0x542617,
    bevel: 0x753925,
    front: 0x3a180d,
    side: 0x250e07,
    trim: 0xca8a04,
    shadow: 0x140703,
    accent: 0xeab308,
  },
  meshFabric: {
    top: 0x1f2430,
    bevel: 0x2d3345,
    front: 0x141720,
    side: 0x0d0f14,
    trim: 0x38bdf8,
    shadow: 0x08090c,
    accent: 0x38bdf8,
  },
};

// ============================================================================
// 3. ABSTRACT BASE ASSET DEFINITION CLASS
// ============================================================================

export abstract class BaseFurnitureAsset {
  public abstract readonly id: string;
  public abstract readonly name: string;
  public abstract readonly category: string;

  public abstract readonly dimensions: AssetDimensions;
  public abstract readonly collisionBox: CollisionBox;
  public abstract readonly shadowSpec: ContactShadowSpec;

  public getSortY(worldY: number): number {
    return worldY + this.collisionBox.y + this.collisionBox.height;
  }

  public abstract drawShadow(g: Graphics, ctx?: RenderContext2D): void;
  public abstract drawBase(g: Graphics, ctx?: RenderContext2D): void;
  public abstract drawFrontFace(g: Graphics, ctx?: RenderContext2D): void;
  public abstract drawTopSurface(g: Graphics, ctx?: RenderContext2D): void;
  public abstract drawSideFace(g: Graphics, ctx?: RenderContext2D): void;
  public drawDetails(_g: Graphics, _ctx?: RenderContext2D): void {}

  public createPixiContainer(worldX: number, worldY: number, ctx: RenderContext2D = { now: 0 }): Container {
    const container = new Container();
    container.x = worldX;
    container.y = worldY;
    container.label = `${this.name}_${this.id}`;

    const shadowG = new Graphics();
    shadowG.label = 'layer_shadow';
    this.drawShadow(shadowG, ctx);
    container.addChild(shadowG);

    const baseG = new Graphics();
    baseG.label = 'layer_base';
    this.drawBase(baseG, ctx);
    container.addChild(baseG);

    const frontG = new Graphics();
    frontG.label = 'layer_frontFace';
    this.drawFrontFace(frontG, ctx);
    container.addChild(frontG);

    const topG = new Graphics();
    topG.label = 'layer_topSurface';
    this.drawTopSurface(topG, ctx);
    container.addChild(topG);

    const sideG = new Graphics();
    sideG.label = 'layer_sideFace';
    this.drawSideFace(sideG, ctx);
    container.addChild(sideG);

    const detailsG = new Graphics();
    detailsG.label = 'layer_details';
    this.drawDetails(detailsG, ctx);
    container.addChild(detailsG);

    return container;
  }
}

// ============================================================================
// 4. DESK ASSET DEFINITIONS
// ============================================================================

export type DeskAccessory =
  | 'coffee'
  | 'espresso'
  | 'headphones'
  | 'lamp'
  | 'plant'
  | 'cables'
  | 'notebook'
  | 'laptop'
  | 'sticky_notes'
  | 'papers'
  | 'energy_drink'
  | 'water_bottle'
  | 'keyboard'
  | 'mouse'
  | 'cert_plaque'
  | 'pen_holder';

export interface DeskAssetConfig {
  id: string;
  width?: number;
  height?: number;
  woodTone?: keyof typeof ASSET_PALETTES;
  monitorSetup?: 'single' | 'dual' | 'triple' | 'curved' | 'vertical_dual' | 'laptop_monitor' | 'executive';
  deskType?: 'developer' | 'designer' | 'manager' | 'systems' | 'data' | 'ops' | 'architect' | 'security';
  accessories?: DeskAccessory[];
  pcTower?: boolean;
}

export class DeskAsset extends BaseFurnitureAsset {
  public readonly id: string;
  public readonly name = 'IsometricWorkstation';
  public readonly category = 'desks';

  public readonly dimensions: AssetDimensions;
  public readonly collisionBox: CollisionBox;
  public readonly shadowSpec: ContactShadowSpec;

  public readonly woodTone: keyof typeof ASSET_PALETTES;
  public readonly monitorSetup: 'single' | 'dual' | 'triple' | 'curved' | 'vertical_dual' | 'laptop_monitor' | 'executive';
  public readonly deskType: 'developer' | 'designer' | 'manager' | 'systems' | 'data' | 'ops' | 'architect' | 'security';
  public readonly accessories: DeskAccessory[];
  public readonly pcTower: boolean;

  constructor(config: DeskAssetConfig) {
    super();
    this.id = config.id;
    const w = config.width || 72;
    const h = config.height || 36;
    this.woodTone = config.woodTone || (config.deskType === 'architect' ? 'walnut' : 'carbon');
    this.monitorSetup = config.monitorSetup || (config.deskType === 'architect' ? 'executive' : 'dual');
    this.deskType = config.deskType || 'developer';
    this.accessories = config.accessories || ['coffee', 'keyboard', 'mouse', 'cables', 'sticky_notes'];
    this.pcTower = config.pcTower !== undefined ? config.pcTower : this.deskType !== 'architect';

    this.dimensions = {
      width: w,
      height: h,
      visualHeight: h + 16,
      depth: 32,
    };

    this.collisionBox = {
      x: 2,
      y: 4,
      width: w - 4,
      height: h - 8,
      zElevation: 0,
    };

    this.shadowSpec = {
      offsetX: -3,
      offsetY: h - 6,
      width: w + 6,
      height: 14,
      opacity: 0.52,
      shape: 'roundedRect',
      cornerRadius: 4,
    };
  }

  public drawShadow(g: Graphics): void {
    const s = this.shadowSpec;
    g.roundRect(s.offsetX, s.offsetY, s.width, s.height, s.cornerRadius || 4)
      .fill({ color: 0x000000, alpha: s.opacity });
    g.roundRect(s.offsetX - 2, s.offsetY + 3, s.width + 4, s.height + 4, 6)
      .fill({ color: 0x000000, alpha: 0.22 });
  }

  public drawBase(g: Graphics): void {
    const w = this.dimensions.width;
    const desktopH = this.dimensions.height - 4;
    const legInset = 4;
    const legW = 3;
    const hasPedestal = w >= 56;

    g.rect(legInset + 2, 8, w - (legInset * 2 + 4), desktopH - 6).fill(0x08090c);

    const legColor = this.deskType === 'architect' ? 0x261b12 : 0x0f172a;
    const highlightColor = this.deskType === 'architect' ? 0x4f3b2c : 0x475569;
    g.rect(legInset, 8, legW, desktopH + 2).fill(legColor);
    g.rect(legInset, 8, 1, desktopH + 2).fill(highlightColor);
    g.rect(legInset - 1, desktopH + 1, legW + 2, 2).fill(0x64748b);

    if (!hasPedestal) {
      g.rect(w - legInset - legW, 8, legW, desktopH + 2).fill(legColor);
      g.rect(w - legInset - legW, 8, 1, desktopH + 2).fill(highlightColor);
      g.rect(w - legInset - legW - 1, desktopH + 1, legW + 2, 2).fill(0x64748b);
    }

    if (this.pcTower) {
      const pcX = legInset + 3;
      const pcY = desktopH - 16;
      g.rect(pcX, pcY, 10, 16).fill(0x0f172a);
      g.rect(pcX + 1, pcY + 1, 8, 14).fill(0x1e293b);
      g.rect(pcX + 3, pcY + 4, 4, 4).fill(0x06b6d4);
      g.rect(pcX + 3, pcY + 10, 4, 3).fill(0x0284c7);
      g.rect(pcX + 7, pcY + 2, 1, 1).fill(0x22c55e);
    }
  }

  public drawFrontFace(g: Graphics): void {
    const w = this.dimensions.width;
    const desktopH = this.dimensions.height - 4;
    const legInset = 4;
    const pal = ASSET_PALETTES[this.woodTone] || ASSET_PALETTES.carbon;
    const hasPedestal = w >= 56;

    g.rect(legInset + 4, 10, w - (legInset * 2 + 8), desktopH - 12).fill(pal.front);
    g.rect(legInset + 4, 10, w - (legInset * 2 + 8), 3).fill({ color: 0x000000, alpha: 0.4 });

    if (hasPedestal) {
      const drawerW = 16;
      const drawerX = w - drawerW - legInset;
      const drawerY = 8;
      const drawerH = desktopH - 6;

      g.rect(drawerX + 1, drawerY, drawerW - 1, drawerH).fill(pal.front);

      const tierH = Math.floor(drawerH / 3);
      for (let i = 0; i < 3; i++) {
        const ty = drawerY + i * tierH;
        g.rect(drawerX + 1, ty, drawerW - 1, 1).fill(0x050608);
        g.rect(drawerX + 2, ty + 1, drawerW - 3, tierH - 2).fill(pal.bevel);
        g.rect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 2).fill(0x94a3b8);
        g.rect(drawerX + 5, ty + Math.floor(tierH / 2) - 1, 6, 1).fill(0xffffff);
      }
    }

    g.rect(0, desktopH - 5, w, 5).fill(pal.front);
    g.rect(0, desktopH - 1, w, 1).fill(pal.shadow);
  }

  public drawTopSurface(g: Graphics): void {
    const w = this.dimensions.width;
    const desktopH = this.dimensions.height - 4;
    const pal = ASSET_PALETTES[this.woodTone] || ASSET_PALETTES.carbon;

    g.rect(1, 1, w - 2, desktopH - 5).fill(pal.top);
    g.rect(1, 1, w - 2, 1).fill(pal.bevel);
    g.rect(1, desktopH - 6, w - 2, 1).fill(pal.bevel);

    if (this.deskType === 'architect') {
      const padW = w - 16;
      const padH = desktopH - 8;
      g.rect(8, 3, padW, padH).fill(0x2a140f);
      g.rect(8, 3, padW, padH).stroke({ color: 0xca8a04, width: 1, alpha: 0.5 });
    } else {
      const matInsetX = Math.floor(w * 0.1);
      const matW = w - matInsetX * 2;
      const matH = desktopH - 9;
      g.rect(matInsetX, 3, matW, matH).fill(0x090a0f);
      g.rect(matInsetX, 3, matW, matH).stroke({ color: pal.accent || 0x38bdf8, width: 1, alpha: 0.35 });
    }
  }

  public drawSideFace(g: Graphics): void {
    const w = this.dimensions.width;
    const desktopH = this.dimensions.height - 4;
    const pal = ASSET_PALETTES[this.woodTone] || ASSET_PALETTES.carbon;

    g.rect(0, 0, 1, desktopH).fill(pal.side);
    g.rect(w - 1, 0, 1, desktopH).fill(pal.side);
  }
}

// ============================================================================
// 5. CHAIR ASSET DEFINITIONS
// ============================================================================

export interface ChairAssetConfig {
  id: string;
  isExecutive?: boolean;
  facing?: 'down' | 'up' | 'left' | 'right';
}

export class ChairAsset extends BaseFurnitureAsset {
  public readonly id: string;
  public readonly name = 'ErgonomicChair';
  public readonly category = 'chairs';

  public readonly dimensions: AssetDimensions;
  public readonly collisionBox: CollisionBox;
  public readonly shadowSpec: ContactShadowSpec;

  public readonly isExecutive: boolean;
  public readonly facing: 'down' | 'up' | 'left' | 'right';

  constructor(config: ChairAssetConfig) {
    super();
    this.id = config.id;
    this.isExecutive = !!config.isExecutive;
    this.facing = config.facing || 'down';

    this.dimensions = {
      width: 20,
      height: 20,
      visualHeight: 24,
      depth: 20,
    };

    this.collisionBox = {
      x: 3,
      y: 3,
      width: 14,
      height: 14,
      zElevation: 0,
    };

    this.shadowSpec = {
      offsetX: 2,
      offsetY: 10,
      width: 16,
      height: 10,
      opacity: 0.48,
      shape: 'ellipse',
    };
  }

  public drawShadow(g: Graphics): void {
    const s = this.shadowSpec;
    g.ellipse(s.offsetX + s.width / 2, s.offsetY + s.height / 2, s.width / 2, s.height / 2)
      .fill({ color: 0x000000, alpha: s.opacity });
  }

  public drawBase(g: Graphics): void {
    const cx = 10;
    const cy = 12;
    const legColor = this.isExecutive ? 0xca8a04 : 0x64748b;

    for (let i = 0; i < 5; i++) {
      const angle = (i * Math.PI * 2) / 5 + Math.PI / 2;
      const rx = cx + Math.cos(angle) * 7;
      const ry = cy + Math.sin(angle) * 4;
      g.moveTo(cx, cy).lineTo(rx, ry).stroke({ color: legColor, width: 1.2 });
      g.rect(rx - 1, ry - 1, 2, 2).fill(0x090a0f);
    }
    g.rect(cx - 1, cy - 4, 2, 4).fill(0xe2e8f0);
  }

  public drawFrontFace(g: Graphics): void {
    const cx = 10;
    const cy = 12;
    const seatW = 14;
    const seatH = 10;
    const seatX = cx - seatW / 2;
    const seatY = cy - 8;
    const pal = this.isExecutive ? ASSET_PALETTES.executiveLeather : ASSET_PALETTES.meshFabric;

    g.rect(seatX, seatY + seatH - 2, seatW, 2).fill(pal.front);
    g.rect(seatX - 2, seatY + 1, 2, 5).fill(0x334155);
    g.rect(seatX + seatW, seatY + 1, 2, 5).fill(0x334155);
  }

  public drawTopSurface(g: Graphics): void {
    const cx = 10;
    const cy = 12;
    const seatW = 14;
    const seatH = 10;
    const seatX = cx - seatW / 2;
    const seatY = cy - 8;
    const pal = this.isExecutive ? ASSET_PALETTES.executiveLeather : ASSET_PALETTES.meshFabric;

    g.roundRect(seatX, seatY, seatW, seatH - 2, 2).fill(pal.top);
    g.rect(seatX + 2, seatY + 1, seatW - 4, 1).fill(pal.bevel);
    g.rect(seatX - 3, seatY, 3, 2).fill(0x090a0f);
    g.rect(seatX + seatW, seatY, 3, 2).fill(0x090a0f);
  }

  public drawSideFace(g: Graphics): void {
    const cx = 10;
    const cy = 12;
    const seatW = 14;
    const seatX = cx - seatW / 2;
    const seatY = cy - 8;
    const pal = this.isExecutive ? ASSET_PALETTES.executiveLeather : ASSET_PALETTES.meshFabric;

    g.rect(seatX, seatY, 1, 8).fill(pal.side);
    g.rect(seatX + seatW - 1, seatY, 1, 8).fill(pal.side);
  }
}

// ============================================================================
// 6. 42U DATACENTER SERVER RACK ASSET
// ============================================================================

export interface ServerRackAssetConfig {
  id: string;
  width?: number;
  height?: number;
}

export class ServerRackAsset extends BaseFurnitureAsset {
  public readonly id: string;
  public readonly name = 'ServerRack42U';
  public readonly category = 'infrastructure';

  public readonly dimensions: AssetDimensions;
  public readonly collisionBox: CollisionBox;
  public readonly shadowSpec: ContactShadowSpec;

  constructor(config: ServerRackAssetConfig) {
    super();
    this.id = config.id;
    const w = config.width || 36;
    const h = config.height || 48;

    this.dimensions = {
      width: w,
      height: h,
      visualHeight: h + 8,
      depth: 32,
    };

    this.collisionBox = {
      x: 1,
      y: 2,
      width: w - 2,
      height: h - 4,
      zElevation: 0,
    };

    this.shadowSpec = {
      offsetX: -2,
      offsetY: h - 4,
      width: w + 4,
      height: 10,
      opacity: 0.65,
      shape: 'roundedRect',
      cornerRadius: 2,
    };
  }

  public drawShadow(g: Graphics): void {
    const s = this.shadowSpec;
    g.roundRect(s.offsetX, s.offsetY, s.width, s.height, s.cornerRadius || 2)
      .fill({ color: 0x000000, alpha: s.opacity });
  }

  public drawBase(g: Graphics): void {
    const w = this.dimensions.width;
    const h = this.dimensions.height;
    g.rect(0, 0, w, h).fill(0x06070a);
    g.rect(1, h - 4, w - 2, 4).fill(0x0f172a);
    g.rect(2, h - 3, w - 4, 1).fill(0x334155);
  }

  public drawFrontFace(g: Graphics): void {
    const w = this.dimensions.width;
    const h = this.dimensions.height;
    const railX = 3;
    const railY = 6;
    const railW = w - 6;
    const railH = h - 10;

    g.rect(railX, railY, railW, railH).fill(0x0b0e14);

    const tierH = 5;
    const numTiers = Math.floor(railH / tierH);

    for (let i = 0; i < numTiers; i++) {
      const ty = railY + i * tierH;
      const col = i % 2 === 0 ? 0x141822 : 0x1c2230;
      g.rect(railX + 1, ty, railW - 2, tierH - 1).fill(col);
      g.rect(railX + 1, ty, railW - 2, 1).fill(0x2b3345);
      g.rect(railX + 3, ty + 1, railW - 14, tierH - 2).fill(0x080a0f);
    }
  }

  public drawTopSurface(g: Graphics): void {
    const w = this.dimensions.width;
    g.rect(1, 1, w - 2, 5).fill(0x1e222d);
    g.rect(1, 1, w - 2, 1).fill(0x333a4c);
    g.circle(w * 0.3, 3.5, 2).fill(0x0a0d14);
    g.circle(w * 0.7, 3.5, 2).fill(0x0a0d14);
  }

  public drawSideFace(g: Graphics): void {
    const w = this.dimensions.width;
    const h = this.dimensions.height;
    g.rect(0, 0, 1, h).fill(0x0a0c10);
    g.rect(w - 1, 0, 1, h).fill(0x0a0c10);
  }
}

// ============================================================================
// 7. FILING & STORAGE CABINET ASSET
// ============================================================================

export interface CabinetAssetConfig {
  id: string;
  width?: number;
  height?: number;
  tiers?: number;
}

export class CabinetAsset extends BaseFurnitureAsset {
  public readonly id: string;
  public readonly name = 'StorageCabinet';
  public readonly category = 'storage';

  public readonly dimensions: AssetDimensions;
  public readonly collisionBox: CollisionBox;
  public readonly shadowSpec: ContactShadowSpec;
  public readonly tiers: number;

  constructor(config: CabinetAssetConfig) {
    super();
    this.id = config.id;
    const w = config.width || 32;
    const h = config.height || 40;
    this.tiers = config.tiers || 3;

    this.dimensions = {
      width: w,
      height: h,
      visualHeight: h + 4,
      depth: 24,
    };

    this.collisionBox = {
      x: 1,
      y: 2,
      width: w - 2,
      height: h - 4,
      zElevation: 0,
    };

    this.shadowSpec = {
      offsetX: -1,
      offsetY: h - 3,
      width: w + 2,
      height: 8,
      opacity: 0.5,
      shape: 'roundedRect',
      cornerRadius: 2,
    };
  }

  public drawShadow(g: Graphics): void {
    const s = this.shadowSpec;
    g.roundRect(s.offsetX, s.offsetY, s.width, s.height, s.cornerRadius || 2)
      .fill({ color: 0x000000, alpha: s.opacity });
  }

  public drawBase(g: Graphics): void {
    const w = this.dimensions.width;
    const h = this.dimensions.height;
    g.rect(0, 0, w, h).fill(0x0f172a);
    g.rect(1, h - 3, w - 2, 3).fill(0x090a0f);
  }

  public drawFrontFace(g: Graphics): void {
    const w = this.dimensions.width;
    const h = this.dimensions.height;
    const topH = 3;
    const usableH = h - topH - 4;
    const drawerH = Math.floor(usableH / this.tiers);

    for (let d = 0; d < this.tiers; d++) {
      const dy = topH + 1 + d * drawerH;
      g.rect(2, dy, w - 4, drawerH - 1).fill(0x1e293b);
      g.rect(2, dy, w - 4, 1).fill(0x334155);
      g.rect(w / 2 - 3, dy + 2, 6, 1.5).fill(0xf8fafc);
      g.rect(w / 2 - 4, dy + Math.floor(drawerH / 2), 8, 1.5).fill(0x94a3b8);
      g.rect(w / 2 - 4, dy + Math.floor(drawerH / 2), 8, 0.8).fill(0xffffff);
    }
  }

  public drawTopSurface(g: Graphics): void {
    const w = this.dimensions.width;
    g.rect(1, 1, w - 2, 3).fill(0x475569);
    g.rect(1, 1, w - 2, 1).fill(0x94a3b8);
  }

  public drawSideFace(g: Graphics): void {
    const w = this.dimensions.width;
    const h = this.dimensions.height;
    g.rect(0, 0, 1, h).fill(0x1e293b);
    g.rect(w - 1, 0, 1, h).fill(0x1e293b);
  }
}

// ============================================================================
// 8. WORKSTATION PRESETS DICTIONARY
// ============================================================================

export const WORKSTATION_PRESETS: Record<string, DeskAssetConfig> = {
  architect_lead: {
    id: 'desk-architect',
    width: 80,
    height: 38,
    woodTone: 'walnut',
    monitorSetup: 'executive',
    deskType: 'architect',
    accessories: ['lamp', 'espresso', 'notebook', 'cert_plaque', 'pen_holder'],
    pcTower: false,
  },
  core_engineer_beta: {
    id: 'desk-beta',
    width: 72,
    height: 36,
    woodTone: 'carbon',
    monitorSetup: 'dual',
    deskType: 'developer',
    accessories: ['coffee', 'headphones', 'keyboard', 'mouse', 'sticky_notes'],
    pcTower: true,
  },
  systems_hash: {
    id: 'desk-hash',
    width: 72,
    height: 36,
    woodTone: 'carbon',
    monitorSetup: 'vertical_dual',
    deskType: 'systems',
    accessories: ['energy_drink', 'keyboard', 'mouse', 'cables', 'sticky_notes'],
    pcTower: true,
  },
  ui_bolt: {
    id: 'desk-bolt',
    width: 72,
    height: 36,
    woodTone: 'carbon',
    monitorSetup: 'curved',
    deskType: 'designer',
    accessories: ['plant', 'coffee', 'keyboard', 'mouse', 'sticky_notes'],
    pcTower: true,
  },
  ml_omega: {
    id: 'desk-omega',
    width: 76,
    height: 36,
    woodTone: 'carbon',
    monitorSetup: 'triple',
    deskType: 'data',
    accessories: ['energy_drink', 'water_bottle', 'keyboard', 'mouse', 'headphones'],
    pcTower: true,
  },
  cicd_forge: {
    id: 'desk-forge',
    width: 72,
    height: 36,
    woodTone: 'carbon',
    monitorSetup: 'curved',
    deskType: 'ops',
    accessories: ['coffee', 'water_bottle', 'keyboard', 'mouse', 'papers'],
    pcTower: true,
  },
  security_watch: {
    id: 'desk-security',
    width: 72,
    height: 36,
    woodTone: 'steelChassis',
    monitorSetup: 'dual',
    deskType: 'security',
    accessories: ['coffee', 'papers', 'keyboard', 'mouse', 'sticky_notes'],
    pcTower: true,
  },
  research_bench: {
    id: 'desk-research',
    width: 70,
    height: 36,
    woodTone: 'carbon',
    monitorSetup: 'laptop_monitor',
    deskType: 'developer',
    accessories: ['notebook', 'coffee', 'pen_holder', 'keyboard', 'mouse'],
    pcTower: true,
  },
  ops_command: {
    id: 'desk-ops',
    width: 72,
    height: 36,
    woodTone: 'oak',
    monitorSetup: 'dual',
    deskType: 'ops',
    accessories: ['coffee', 'papers', 'sticky_notes', 'keyboard', 'mouse'],
    pcTower: true,
  },
};

// ============================================================================
// 9. HIGH-PERFORMANCE PIXIJS ASSET PRELOADER & SPRITE REGISTRY
// ============================================================================

export interface AssetLoadProgress {
  total: number;
  loaded: number;
  percentage: number;
  currentItem: string;
  isComplete: boolean;
}

export class PixiAssetLoader {
  private textures = new Map<string, Texture>();
  private isPreloading = false;
  private isLoaded = false;
  private loadProgress: AssetLoadProgress = {
    total: 0,
    loaded: 0,
    percentage: 0,
    currentItem: '',
    isComplete: false,
  };
  private listeners = new Set<(progress: AssetLoadProgress) => void>();

  /**
   * Subscribes a listener to loading progress updates.
   */
  public onProgress(cb: (progress: AssetLoadProgress) => void): () => void {
    this.listeners.add(cb);
    cb(this.loadProgress);
    return () => this.listeners.delete(cb);
  }

  private notify(item: string) {
    this.loadProgress.currentItem = item;
    this.loadProgress.percentage = this.loadProgress.total > 0
      ? Math.round((this.loadProgress.loaded / this.loadProgress.total) * 100)
      : 100;
    this.loadProgress.isComplete = this.isLoaded;
    this.listeners.forEach((cb) => cb({ ...this.loadProgress }));
  }

  /**
   * Helper to rasterize canvas callback to a PixiJS Texture.
   */
  public createTextureFromCanvas(
    width: number,
    height: number,
    padding: number,
    renderFn: (ctx: CanvasRenderingContext2D, ox: number, oy: number) => void
  ): Texture {
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(width + padding * 2);
    canvas.height = Math.ceil(height + padding * 2);
    const ctx = canvas.getContext('2d');
    if (!ctx) return Texture.WHITE;

    ctx.imageSmoothingEnabled = false;
    renderFn(ctx, padding, padding);

    const source = new CanvasSource({ resource: canvas });
    return new Texture({ source });
  }

  /**
   * Preloads and compiles all office furniture, compute racks, appliances, and environment assets into GPU textures.
   */
  public async preloadAll(): Promise<Map<string, Texture>> {
    if (this.isLoaded) return this.textures;
    if (this.isPreloading) {
      return new Promise((resolve) => {
        const unsub = this.onProgress((p) => {
          if (p.isComplete) {
            unsub();
            resolve(this.textures);
          }
        });
      });
    }

    this.isPreloading = true;

    // Calculate total assets to preload
    const tasks: Array<{ key: string; name: string; run: () => Texture }> = [];

    // 1. Desks
    OFFICE_2D_LAYOUT.desks.forEach((desk) => {
      const key = `desk_${desk.id}_${desk.deskType || 'dev'}_${desk.woodTone || 'carbon'}_${desk.monitorSetup || 'dual'}_${desk.accessories?.join('-') || ''}`;
      tasks.push({
        key,
        name: `Workstation: ${desk.id}`,
        run: () => {
          return this.createTextureFromCanvas(desk.width, desk.height + 24, 16, (ctx, ox, oy) => {
            const dummyDesk = { ...desk, x: ox, y: oy + 10 };
            drawDeskShadow(ctx, dummyDesk);
            draw3DDesk(ctx, dummyDesk, 0);
          });
        },
      });
    });

    // 2. Chairs (all directions and variants)
    const chairFacings: Array<'down' | 'up' | 'left' | 'right'> = ['down', 'up', 'left', 'right'];
    chairFacings.forEach((facing) => {
      [false, true].forEach((isExec) => {
        const key = `chair_${facing}_${isExec ? 'exec' : 'std'}`;
        tasks.push({
          key,
          name: `Chair (${facing} ${isExec ? 'Executive' : 'Mesh'})`,
          run: () => {
            return this.createTextureFromCanvas(24, 24, 8, (ctx, ox, oy) => {
              drawChairShadow(ctx, ox, oy);
              draw3DChair(ctx, ox, oy, facing, false, isExec);
            });
          },
        });
      });
    });

    // 3. Furniture (Sofas, Conference Tables, Plants, Racks)
    OFFICE_2D_LAYOUT.furniture.forEach((f) => {
      tasks.push({
        key: `furniture_${f.id}`,
        name: `Furniture: ${f.id}`,
        run: () => {
          return this.createTextureFromCanvas(f.width, f.height, 12, (ctx, ox, oy) => {
            const dummy = { ...f, x: ox, y: oy };
            if (f.type === 'server_rack') {
              drawServerRack3D(ctx, dummy, 0);
            } else if (f.type === 'sofa') {
              if (f.id.includes('bench')) drawZenBench(ctx, dummy);
              else drawPlushSofa(ctx, dummy);
            } else if (f.type === 'plant') {
              drawPottedPlant(ctx, dummy);
            } else if (f.type === 'table') {
              if (f.id === 'sofa-table') drawCoffeeTable(ctx, dummy);
              else if (f.id === 'cafe-round-table') drawRoundCafeTable(ctx, dummy);
              else drawConferenceTable(ctx, dummy, 0);
            }
          });
        },
      });
    });

    // 4. Interactive POIs (Arcades, Vending Machines, Espresso, Water Coolers, Server, Whiteboard, Bookshelf, Zen Fountain)
    OFFICE_2D_LAYOUT.pois.forEach((poi) => {
      [0, 1, 2, 3].forEach((frame) => {
        const key = `poi_${poi.id}_f${frame}`;
        tasks.push({
          key,
          name: `POI: ${poi.name} (Frame ${frame})`,
          run: () => {
            return this.createTextureFromCanvas(poi.width, poi.height, 12, (ctx, ox, oy) => {
              const dummy = { ...poi, x: ox, y: oy };
              if (poi.type === 'arcade') drawArcadeCabinet(ctx, dummy, frame * 200, false);
              else if (poi.type === 'vending_machine') drawVendingMachine(ctx, dummy, frame * 300);
              else if (poi.type === 'server_rack') drawServerRack3D(ctx, dummy, frame * 250);
              else if (poi.type === 'coffee_machine') drawEspressoMachine(ctx, dummy, frame * 200, false);
              else if (poi.type === 'water_cooler') drawWaterCooler(ctx, dummy, frame * 250);
              else if (poi.type === 'whiteboard') drawWhiteboard(ctx, dummy);
              else if (poi.type === 'bookshelf') drawBookshelf(ctx, dummy);
              else if (poi.type === 'fountain') drawZenFountain(ctx, dummy, frame * 200);
            });
          },
        });
      });
    });

    // 5. Environmental Props (Filing Cabinets, Printers, Bins)
    if (OFFICE_2D_LAYOUT.environmentalProps) {
      OFFICE_2D_LAYOUT.environmentalProps.forEach((prop) => {
        const key = `prop_${prop.id}_${prop.type}`;
        tasks.push({
          key,
          name: `Prop: ${prop.type} (${prop.id})`,
          run: () => {
            return this.createTextureFromCanvas(prop.width, prop.height, 8, (ctx, ox, oy) => {
              const dummy = { ...prop, x: ox, y: oy };
              drawEnvironmentalProp(ctx, dummy, 0);
            });
          },
        });
      });
    }

    this.loadProgress.total = tasks.length;
    this.loadProgress.loaded = 0;

    // Process tasks sequentially with small yielding pauses to keep UI responsive
    for (const task of tasks) {
      try {
        const tex = task.run();
        this.textures.set(task.key, tex);
      } catch (err) {
        console.warn(`[PixiAssetLoader] Failed generating texture for ${task.key}`, err);
      }
      this.loadProgress.loaded++;
      this.notify(task.name);
      // Fast yield
      if (this.loadProgress.loaded % 10 === 0) {
        await new Promise((r) => setTimeout(r, 0));
      }
    }

    this.isPreloading = false;
    this.isLoaded = true;
    this.loadProgress.isComplete = true;
    this.notify('Ready');

    return this.textures;
  }

  public getTexture(key: string): Texture {
    return this.textures.get(key) || Texture.WHITE;
  }

  public getSprite(key: string): Sprite {
    return new Sprite(this.getTexture(key));
  }

  public has(key: string): boolean {
    return this.textures.has(key);
  }

  public isReady(): boolean {
    return this.isLoaded;
  }

  public getProgress(): AssetLoadProgress {
    return { ...this.loadProgress };
  }

  public clear(): void {
    this.textures.forEach((tex) => tex.destroy(true));
    this.textures.clear();
    this.isLoaded = false;
    this.isPreloading = false;
  }

  /**
   * Convenience helpers for specific sprite keys
   */
  public getDeskTexture(desk: Desk2D): Texture {
    const key = `desk_${desk.id}_${desk.deskType || 'dev'}_${desk.woodTone || 'carbon'}_${desk.monitorSetup || 'dual'}_${desk.accessories?.join('-') || ''}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(desk.width, desk.height + 24, 16, (ctx, ox, oy) => {
      const dummyDesk = { ...desk, x: ox, y: oy + 10 };
      drawDeskShadow(ctx, dummyDesk);
      draw3DDesk(ctx, dummyDesk, 0);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getServerRackTexture(rack: Furniture2D | InteractivePOI, frame = 0): Texture {
    const key = `poi_${rack.id}_f${frame % 4}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(rack.width, rack.height, 12, (ctx, ox, oy) => {
      const dummy = { ...rack, x: ox, y: oy };
      drawServerRack3D(ctx, dummy, frame * 250);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getArcadeCabinetTexture(poi: InteractivePOI, frame = 0): Texture {
    const key = `poi_${poi.id}_f${frame % 4}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(poi.width, poi.height, 12, (ctx, ox, oy) => {
      const dummy = { ...poi, x: ox, y: oy };
      drawArcadeCabinet(ctx, dummy, frame * 200, false);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getVendingMachineTexture(poi: InteractivePOI, frame = 0): Texture {
    const key = `poi_${poi.id}_f${frame % 3}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(poi.width, poi.height, 12, (ctx, ox, oy) => {
      const dummy = { ...poi, x: ox, y: oy };
      drawVendingMachine(ctx, dummy, frame * 300);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getFilingCabinetTexture(prop: EnvironmentalProp2D): Texture {
    const key = `prop_${prop.id}_${prop.type}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(prop.width, prop.height, 8, (ctx, ox, oy) => {
      const dummy = { ...prop, x: ox, y: oy };
      drawEnvironmentalProp(ctx, dummy, 0);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getChairTexture(facing: 'down' | 'up' | 'left' | 'right', isExecutive = false): Texture {
    const key = `chair_${facing}_${isExecutive ? 'exec' : 'std'}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(24, 24, 8, (ctx, ox, oy) => {
      drawChairShadow(ctx, ox, oy);
      draw3DChair(ctx, ox, oy, facing, false, isExecutive);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getTableTexture(table: Furniture2D): Texture {
    const key = `furniture_${table.id}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(table.width, table.height, 12, (ctx, ox, oy) => {
      const dummy = { ...table, x: ox, y: oy };
      if (table.id === 'sofa-table') drawCoffeeTable(ctx, dummy);
      else if (table.id === 'cafe-round-table') drawRoundCafeTable(ctx, dummy);
      else drawConferenceTable(ctx, dummy, 0);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getSofaTexture(sofa: Furniture2D): Texture {
    const key = `furniture_${sofa.id}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(sofa.width, sofa.height, 12, (ctx, ox, oy) => {
      const dummy = { ...sofa, x: ox, y: oy };
      if (sofa.id.includes('bench')) drawZenBench(ctx, dummy);
      else drawPlushSofa(ctx, dummy);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getPlantTexture(furniture: Furniture2D): Texture {
    const key = `furniture_${furniture.id}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(furniture.width, furniture.height, 10, (ctx, ox, oy) => {
      const dummy = { ...furniture, x: ox, y: oy };
      drawPottedPlant(ctx, dummy);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getWhiteboardTexture(poi: InteractivePOI): Texture {
    const key = `poi_${poi.id}_f0`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(poi.width, poi.height, 10, (ctx, ox, oy) => {
      const dummy = { ...poi, x: ox, y: oy };
      drawWhiteboard(ctx, dummy);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getBookshelfTexture(poi: InteractivePOI): Texture {
    const key = `poi_${poi.id}_f0`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(poi.width, poi.height, 10, (ctx, ox, oy) => {
      const dummy = { ...poi, x: ox, y: oy };
      drawBookshelf(ctx, dummy);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getEspressoMachineTexture(poi: InteractivePOI, frame = 0): Texture {
    const key = `poi_${poi.id}_f${frame % 4}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(poi.width, poi.height, 10, (ctx, ox, oy) => {
      const dummy = { ...poi, x: ox, y: oy };
      drawEspressoMachine(ctx, dummy, frame * 200, false);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getWaterCoolerTexture(poi: InteractivePOI, frame = 0): Texture {
    const key = `poi_${poi.id}_f${frame % 3}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(poi.width, poi.height, 8, (ctx, ox, oy) => {
      const dummy = { ...poi, x: ox, y: oy };
      drawWaterCooler(ctx, dummy, frame * 250);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getZenFountainTexture(poi: InteractivePOI, frame = 0): Texture {
    const key = `poi_${poi.id}_f${frame % 4}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(poi.width, poi.height, 12, (ctx, ox, oy) => {
      const dummy = { ...poi, x: ox, y: oy };
      drawZenFountain(ctx, dummy, frame * 200);
    });
    this.textures.set(key, tex);
    return tex;
  }

  public getPropTexture(prop: EnvironmentalProp2D, now = 0): Texture {
    const key = `prop_${prop.id}_${prop.type}`;
    if (this.textures.has(key)) return this.textures.get(key)!;
    const tex = this.createTextureFromCanvas(prop.width, prop.height, 8, (ctx, ox, oy) => {
      const dummy = { ...prop, x: ox, y: oy };
      drawEnvironmentalProp(ctx, dummy, now);
    });
    this.textures.set(key, tex);
    return tex;
  }
}

export const pixiAssetLoader = new PixiAssetLoader();

/**
 * React Hook for preloading PixiJS office sprite sheets and monitoring progress.
 */
export function useOfficeAssetPreloader() {
  const [progress, setProgress] = useState<AssetLoadProgress>(() => pixiAssetLoader.getProgress());

  useEffect(() => {
    const unsub = pixiAssetLoader.onProgress((p) => {
      setProgress(p);
    });

    if (!pixiAssetLoader.isReady()) {
      pixiAssetLoader.preloadAll().catch((err) => {
        console.error('[useOfficeAssetPreloader] Preload failed', err);
      });
    }

    return unsub;
  }, []);

  return {
    ...progress,
    loader: pixiAssetLoader,
    isReady: progress.isComplete,
  };
}

// ============================================================================
// 10. CENTRALIZED EXPORTS
// ============================================================================

export const PixelAssets = {
  loader: pixiAssetLoader,
  palettes: ASSET_PALETTES,
  presets: WORKSTATION_PRESETS,
  DeskAsset,
  ChairAsset,
  ServerRackAsset,
  CabinetAsset,
  useOfficeAssetPreloader,

  createDesk: (config: DeskAssetConfig) => new DeskAsset(config),
  createPresetDesk: (presetKey: keyof typeof WORKSTATION_PRESETS, overrideId?: string) => {
    const preset = WORKSTATION_PRESETS[presetKey] ?? WORKSTATION_PRESETS.core_engineer_beta;
    if (!preset) {
      throw new Error(`Unknown workstation preset: ${presetKey}`);
    }
    return new DeskAsset({
      ...preset,
      id: overrideId || preset.id,
    });
  },
  createChair: (config: ChairAssetConfig) => new ChairAsset(config),
  createServerRack: (config: ServerRackAssetConfig) => new ServerRackAsset(config),
  createCabinet: (config: CabinetAssetConfig) => new CabinetAsset(config),
};

export default PixelAssets;
