import { Texture } from 'pixi.js';
import type { Desk2D, EnvironmentalProp2D, Furniture2D, InteractivePOI } from '../office2d/types';
import { pixiAssetLoader } from '@/lib/PixelAssets';

/**
 * Texture Cache & Sprite Factory for PixiJS assets, backed by the central PixiAssetLoader in src/lib/PixelAssets.ts.
 */
class TextureCacheManager {
  getDeskTexture(desk: Desk2D): Texture {
    return pixiAssetLoader.getDeskTexture(desk);
  }

  getServerRackTexture(rack: Furniture2D | InteractivePOI, frame = 0): Texture {
    return pixiAssetLoader.getServerRackTexture(rack, frame);
  }

  getArcadeCabinetTexture(poi: InteractivePOI, frame = 0): Texture {
    return pixiAssetLoader.getArcadeCabinetTexture(poi, frame);
  }

  getVendingMachineTexture(poi: InteractivePOI, frame = 0): Texture {
    return pixiAssetLoader.getVendingMachineTexture(poi, frame);
  }

  getFilingCabinetTexture(prop: EnvironmentalProp2D): Texture {
    return pixiAssetLoader.getFilingCabinetTexture(prop);
  }

  getConferenceTableTexture(table: Furniture2D): Texture {
    return pixiAssetLoader.getTableTexture(table);
  }

  getBookshelfTexture(poi: InteractivePOI): Texture {
    return pixiAssetLoader.getBookshelfTexture(poi);
  }

  getWhiteboardTexture(poi: InteractivePOI): Texture {
    return pixiAssetLoader.getWhiteboardTexture(poi);
  }

  getEspressoMachineTexture(poi: InteractivePOI, frame = 0): Texture {
    return pixiAssetLoader.getEspressoMachineTexture(poi, frame);
  }

  getWaterCoolerTexture(poi: InteractivePOI, frame = 0): Texture {
    return pixiAssetLoader.getWaterCoolerTexture(poi, frame);
  }

  getPlantTexture(furniture: Furniture2D): Texture {
    return pixiAssetLoader.getPlantTexture(furniture);
  }

  getChairTexture(facing: 'down' | 'up' | 'left' | 'right', isExecutive = false): Texture {
    return pixiAssetLoader.getChairTexture(facing, isExecutive);
  }

  getSofaTexture(sofa: Furniture2D): Texture {
    return pixiAssetLoader.getSofaTexture(sofa);
  }

  getTableTexture(table: Furniture2D): Texture {
    return pixiAssetLoader.getTableTexture(table);
  }

  getZenFountainTexture(poi: InteractivePOI, frame = 0): Texture {
    return pixiAssetLoader.getZenFountainTexture(poi, frame);
  }

  getPropTexture(prop: EnvironmentalProp2D, now = 0): Texture {
    return pixiAssetLoader.getPropTexture(prop, now);
  }

  clear() {
    pixiAssetLoader.clear();
  }
}

export const pixiTextureManager = new TextureCacheManager();
export { pixiAssetLoader };
