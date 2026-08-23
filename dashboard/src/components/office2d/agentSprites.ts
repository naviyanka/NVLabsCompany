import type { Agent2D } from './types';

/**
 * 2D Pixel Sprite Renderer for AI Agents
 * Draws crisp retro pixel-art characters directly to HTML5 Canvas
 */

export function drawPixelAgent(
  ctx: CanvasRenderingContext2D,
  agent: Agent2D,
  isSelected: boolean,
  isHovered: boolean
) {
  const { x, y, facing, walkFrame, isMoving, sprite, state2D, bubble } = agent;
  const isTyping = state2D === 'working_at_desk';

  ctx.save();
  ctx.translate(Math.round(x), Math.round(y));

  // 1. Selection & Hover Aura / Ring
  if (isSelected || isHovered) {
    ctx.beginPath();
    ctx.ellipse(0, 4, 18, 9, 0, 0, Math.PI * 2);
    ctx.fillStyle = isSelected
      ? 'rgba(255, 176, 32, 0.45)'
      : 'rgba(56, 189, 248, 0.35)';
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = isSelected ? '#FFB020' : '#38BDF8';
    ctx.stroke();
  } else {
    // Subtle shadow underneath character
    ctx.beginPath();
    ctx.ellipse(0, 4, 12, 5, 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
    ctx.fill();
  }

  // 2. Head bobbing & leg step offset calculations (continuous gait-based when available)
  let bobY = 0;
  let legOffset = 0;
  let armBob = 0;

  if (isMoving) {
    if (agent.distanceTraveled !== undefined) {
      const gaitCycle = (agent.distanceTraveled / 9) * Math.PI * 2;
      bobY = Math.round(Math.abs(Math.sin(gaitCycle)) * -2);
      legOffset = Math.round(Math.sin(gaitCycle) * 3);
      armBob = Math.round(Math.sin(gaitCycle) * 2.5);
    } else {
      bobY = walkFrame % 2 === 1 ? -2 : 0;
      legOffset = walkFrame === 1 ? -3 : walkFrame === 3 ? 3 : 0;
      armBob = walkFrame === 1 ? 2 : walkFrame === 3 ? -2 : 0;
    }
  } else if (isTyping) {
    bobY = Math.round(Math.sin(Date.now() / 150) * 1);
  }

  // 3. Render Legs / Pants & Shoes (Clear Color-Blocking)
  const pantsColor = sprite.pantsColor || '#1E293B';
  ctx.fillStyle = pantsColor;
  if (facing === 'down' || facing === 'up') {
    // Left leg
    ctx.fillRect(-5, -3 + (legOffset < 0 ? legOffset : 0), 4, 7 - (legOffset < 0 ? legOffset : 0));
    // Right leg
    ctx.fillRect(1, -3 + (legOffset > 0 ? -legOffset : 0), 4, 7 - (legOffset > 0 ? -legOffset : 0));

    // Shoes
    ctx.fillStyle = '#0F172A';
    ctx.fillRect(-6, 3 + (legOffset < 0 ? legOffset : 0), 5, 3);
    ctx.fillRect(1, 3 + (legOffset > 0 ? -legOffset : 0), 5, 3);
    // Shoe tip highlight
    ctx.fillStyle = '#334155';
    ctx.fillRect(-5, 3 + (legOffset < 0 ? legOffset : 0), 2, 1);
    ctx.fillRect(2, 3 + (legOffset > 0 ? -legOffset : 0), 2, 1);
  } else if (facing === 'left') {
    ctx.fillRect(-3 + legOffset, -3, 6, 7);
    ctx.fillStyle = '#0F172A';
    ctx.fillRect(-5 + legOffset, 3, 7, 3);
    ctx.fillStyle = '#334155';
    ctx.fillRect(-4 + legOffset, 3, 2, 1);
  } else {
    // right
    ctx.fillRect(-3 - legOffset, -3, 6, 7);
    ctx.fillStyle = '#0F172A';
    ctx.fillRect(-2 - legOffset, 3, 7, 3);
    ctx.fillStyle = '#334155';
    ctx.fillRect(2 - legOffset, 3, 2, 1);
  }

  // 4. Render Torso / Shirt / Jacket (Distinct color blocking separate from limbs & pants)
  const torsoColor = sprite.outfitColor || '#2563EB';
  const sleeveColor = sprite.outfitColor || '#1D4ED8';
  
  // Torso main body
  ctx.fillStyle = torsoColor;
  ctx.fillRect(-7, -15 + bobY, 14, 13);

  // Shirt collar / neckline / tie / belt detail
  if (facing === 'down') {
    // V-neck / collar
    ctx.fillStyle = sprite.skinTone || '#FDE047';
    ctx.fillRect(-2, -15 + bobY, 4, 3);
    // Shirt button placket / center seam
    ctx.fillStyle = 'rgba(0, 0, 0, 0.2)';
    ctx.fillRect(-0.5, -12 + bobY, 1, 9);
    // Belt line
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(-7, -3 + bobY, 14, 1.5);
    ctx.fillStyle = '#f59e0b';
    ctx.fillRect(-1.5, -3 + bobY, 3, 1.5); // belt buckle
  } else if (facing === 'left' || facing === 'right') {
    // Side belt line
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(-6, -3 + bobY, 12, 1.5);
  }

  // Labcoat / Armor / Hoodie Overlays
  if (sprite.accessory === 'labcoat') {
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(-8, -15 + bobY, 3.5, 13);
    ctx.fillRect(4.5, -15 + bobY, 3.5, 13);
    ctx.fillStyle = '#E2E8F0';
    ctx.fillRect(-8, -3 + bobY, 16, 2);
  } else if (sprite.accessory === 'armor') {
    ctx.fillStyle = '#78350F';
    ctx.fillRect(-6, -14 + bobY, 12, 8);
    ctx.fillStyle = '#F59E0B';
    ctx.fillRect(-2, -12 + bobY, 4, 4);
  }

  // 5. Arms & Hands (Sleeves matching outfit + distinct Skin Tone Hands)
  if (isTyping) {
    // Sleeves
    ctx.fillStyle = sleeveColor;
    ctx.fillRect(-8, -13 + bobY, 4, 7);
    ctx.fillRect(4, -13 + bobY, 4, 7);
    // Typing hands out front
    ctx.fillStyle = sprite.skinTone || '#FDE047';
    const typingAnim = Math.sin(Date.now() / 80) > 0;
    ctx.fillRect(-6, -5 + bobY + (typingAnim ? -1 : 1), 3.5, 3.5);
    ctx.fillRect(2.5, -5 + bobY + (typingAnim ? 1 : -1), 3.5, 3.5);
  } else if (facing === 'down') {
    // Left & right sleeves
    ctx.fillStyle = sleeveColor;
    ctx.fillRect(-9, -14 + bobY + armBob, 3, 7);
    ctx.fillRect(6, -14 + bobY - armBob, 3, 7);
    // Left & right hands (skin tone)
    ctx.fillStyle = sprite.skinTone || '#FDE047';
    ctx.fillRect(-9, -7 + bobY + armBob, 3, 3);
    ctx.fillRect(6, -7 + bobY - armBob, 3, 3);
  } else if (facing === 'up') {
    ctx.fillStyle = sleeveColor;
    ctx.fillRect(-9, -14 + bobY - armBob, 3, 8);
    ctx.fillRect(6, -14 + bobY + armBob, 3, 8);
  } else if (facing === 'left') {
    ctx.fillStyle = sleeveColor;
    ctx.fillRect(-5 + (isMoving ? armBob : 0), -13 + bobY, 4, 7);
    ctx.fillStyle = sprite.skinTone || '#FDE047';
    ctx.fillRect(-6 + (isMoving ? armBob : 0), -6 + bobY, 3, 3);
  } else {
    // right
    ctx.fillStyle = sleeveColor;
    ctx.fillRect(1 - (isMoving ? armBob : 0), -13 + bobY, 4, 7);
    ctx.fillStyle = sprite.skinTone || '#FDE047';
    ctx.fillRect(3 - (isMoving ? armBob : 0), -6 + bobY, 3, 3);
  }

  // Soft Top-Down Specular Shoulder Highlight
  ctx.fillStyle = 'rgba(255, 255, 255, 0.28)';
  ctx.fillRect(-7, -15 + bobY, 14, 1.5);

  // 6. Head & Face (Crisp Facial Details, Eyes & Silhouette)
  // Head base
  const skinTone = sprite.skinTone || '#FDE047';
  ctx.fillStyle = skinTone;
  ctx.fillRect(-6, -26 + bobY, 12, 11);

  // Soft Head Specular Crown Highlight
  ctx.fillStyle = 'rgba(255, 255, 255, 0.22)';
  ctx.fillRect(-5, -26 + bobY, 10, 1);

  // Eyes & Features based on direction
  if (facing === 'down') {
    // 2 crisp front-facing eyes with whites/shines
    ctx.fillStyle = '#0F172A';
    ctx.fillRect(-4, -21 + bobY, 2.5, 2.5);
    ctx.fillRect(1.5, -21 + bobY, 2.5, 2.5);
    // Eye specular shine dots
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(-4, -21 + bobY, 1, 1);
    ctx.fillRect(1.5, -21 + bobY, 1, 1);

    // Subtle nose / mouth line
    ctx.fillStyle = 'rgba(0, 0, 0, 0.15)';
    ctx.fillRect(-0.5, -19 + bobY, 1, 1);
    ctx.fillRect(-1.5, -17 + bobY, 3, 0.8);

    // Glasses / Visor
    if (sprite.accessory === 'glasses') {
      ctx.strokeStyle = sprite.accessoryColor || '#FFB020';
      ctx.lineWidth = 1.2;
      ctx.strokeRect(-5, -22 + bobY, 4, 3.5);
      ctx.strokeRect(1, -22 + bobY, 4, 3.5);
      ctx.beginPath();
      ctx.moveTo(-1, -20.5 + bobY);
      ctx.lineTo(1, -20.5 + bobY);
      ctx.stroke();
    } else if (sprite.accessory === 'visor') {
      ctx.fillStyle = sprite.accessoryColor || '#06B6D4';
      ctx.fillRect(-6, -22 + bobY, 12, 3.5);
      ctx.fillStyle = '#FFFFFF';
      ctx.fillRect(-5, -22 + bobY, 3, 1);
    }
  } else if (facing === 'left') {
    ctx.fillStyle = '#0F172A';
    ctx.fillRect(-5, -21 + bobY, 2.5, 2.5);
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(-5, -21 + bobY, 1, 1);
    if (sprite.accessory === 'glasses') {
      ctx.strokeStyle = sprite.accessoryColor || '#FFB020';
      ctx.lineWidth = 1.2;
      ctx.strokeRect(-6, -22 + bobY, 4, 3.5);
    } else if (sprite.accessory === 'visor') {
      ctx.fillStyle = sprite.accessoryColor || '#06B6D4';
      ctx.fillRect(-6, -22 + bobY, 6, 3.5);
    }
  } else if (facing === 'right') {
    ctx.fillStyle = '#0F172A';
    ctx.fillRect(2.5, -21 + bobY, 2.5, 2.5);
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(3.5, -21 + bobY, 1, 1);
    if (sprite.accessory === 'glasses') {
      ctx.strokeStyle = sprite.accessoryColor || '#FFB020';
      ctx.lineWidth = 1.2;
      ctx.strokeRect(1.5, -22 + bobY, 4, 3.5);
    } else if (sprite.accessory === 'visor') {
      ctx.fillStyle = sprite.accessoryColor || '#06B6D4';
      ctx.fillRect(0, -22 + bobY, 6, 3.5);
    }
  }

  // 7. Hair (Head-Top Shape, Fringe & Directional Volume)
  const hairColor = sprite.hairColor || '#334155';
  ctx.fillStyle = hairColor;
  if (facing === 'up') {
    // Full back hair volume
    ctx.fillRect(-7, -28 + bobY, 14, 13);
    // Back hair highlight rim
    ctx.fillStyle = 'rgba(255, 255, 255, 0.2)';
    ctx.fillRect(-6, -28 + bobY, 12, 1.5);
  } else {
    // Head-top dome & sideburns
    ctx.fillRect(-7, -28 + bobY, 14, 5);
    ctx.fillRect(-7, -26 + bobY, 2.5, 6);
    ctx.fillRect(4.5, -26 + bobY, 2.5, 6);

    // Front fringe / bangs across forehead
    ctx.fillRect(-5, -26 + bobY, 10, 2);

    // Top-down specular highlight on hair crown
    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
    ctx.fillRect(-5, -28 + bobY, 10, 1.5);

    ctx.fillStyle = hairColor;
    if (sprite.hairStyle === 'spiky') {
      ctx.fillRect(-6, -30 + bobY, 3, 3);
      ctx.fillRect(-1.5, -31 + bobY, 3, 4);
      ctx.fillRect(3, -29 + bobY, 3, 2);
    } else if (sprite.hairStyle === 'ponytail' && (facing === 'left' || facing === 'right')) {
      const pX = facing === 'left' ? 5 : -8;
      ctx.fillRect(pX, -24 + bobY, 3.5, 9);
    } else if (sprite.hairStyle === 'long') {
      ctx.fillRect(-8, -24 + bobY, 3, 11);
      ctx.fillRect(5, -24 + bobY, 3, 11);
    }
  }

  // Headphones
  if (sprite.accessory === 'headphones') {
    ctx.fillStyle = sprite.accessoryColor || '#EAB308';
    ctx.fillRect(-9, -23 + bobY, 3, 6);
    ctx.fillRect(6, -23 + bobY, 3, 6);
    // Headband over top
    ctx.strokeStyle = sprite.accessoryColor || '#EAB308';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(0, -26 + bobY, 8, Math.PI, 0);
    ctx.stroke();
  }

  // 8. Overhead Name Badge & Status Dot (Clean Sans-Serif Floating Nameplate)
  ctx.font = 'bold 9.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
  const nameWidth = ctx.measureText(agent.name).width;
  const badgeWidth = nameWidth + 18;
  const badgeY = -34 + bobY;

  // Soft badge shadow
  ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
  ctx.beginPath();
  ctx.roundRect(-badgeWidth / 2 + 1, badgeY - 10, badgeWidth, 14, 4);
  ctx.fill();

  // Badge background
  ctx.fillStyle = '#0c101af5';
  ctx.beginPath();
  ctx.roundRect(-badgeWidth / 2, badgeY - 11, badgeWidth, 14, 4);
  ctx.fill();

  // Status color mapping
  const statusColor =
    agent.status === 'working'
      ? '#10B981'
      : agent.status === 'review'
      ? '#A855F7'
      : agent.status === 'idle'
      ? '#F59E0B'
      : '#64748B';

  ctx.strokeStyle = isSelected ? '#38BDF8' : 'rgba(255, 255, 255, 0.15)';
  ctx.lineWidth = 1;
  ctx.stroke();

  // Status indicator dot
  ctx.beginPath();
  ctx.arc(-badgeWidth / 2 + 7, badgeY - 4, 2.5, 0, Math.PI * 2);
  ctx.fillStyle = statusColor;
  ctx.fill();

  // Agent Name text
  ctx.fillStyle = isSelected ? '#38BDF8' : '#F1F5F9';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(agent.name, -badgeWidth / 2 + 13, badgeY - 4);

  // 9. Thought / Speech Bubble
  if (bubble && bubble.expiresAt > Date.now()) {
    drawSpeechBubble(ctx, bubble.text, bubble.emoji, badgeY - 18, isSelected);
  }

  ctx.restore();
}

/**
 * Renders retro speech/thought bubbles with high-contrast text and emojis
 */
function drawSpeechBubble(
  ctx: CanvasRenderingContext2D,
  text: string,
  emoji: string | undefined,
  bubbleBottomY: number,
  isSelected: boolean
) {
  ctx.font = '11px sans-serif';
  const displayStr = emoji ? `${emoji} ${text}` : text;
  const textMetrics = ctx.measureText(displayStr);
  const paddingX = 8;
  const bubbleWidth = Math.min(Math.max(textMetrics.width + paddingX * 2, 60), 220);
  const bubbleHeight = 22;
  const bubbleY = bubbleBottomY - bubbleHeight;

  ctx.save();

  // Bubble Shadow
  ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
  ctx.shadowBlur = 6;
  ctx.shadowOffsetY = 2;

  // Bubble Box
  ctx.fillStyle = '#FFFFFF';
  ctx.beginPath();
  ctx.roundRect(-bubbleWidth / 2, bubbleY, bubbleWidth, bubbleHeight, 6);
  ctx.fill();

  // Triangle Tail pointing to agent head
  ctx.beginPath();
  ctx.moveTo(-4, bubbleY + bubbleHeight);
  ctx.lineTo(0, bubbleY + bubbleHeight + 5);
  ctx.lineTo(4, bubbleY + bubbleHeight);
  ctx.closePath();
  ctx.fillStyle = '#FFFFFF';
  ctx.fill();

  ctx.restore();

  // Border
  ctx.strokeStyle = isSelected ? '#FFB020' : '#0A0A0B';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(-bubbleWidth / 2, bubbleY, bubbleWidth, bubbleHeight, 6);
  ctx.stroke();

  // Text
  ctx.fillStyle = '#0F172A';
  ctx.font = 'bold 10px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  
  // Truncate if text is long
  let renderedText = displayStr;
  if (renderedText.length > 28) {
    renderedText = renderedText.substring(0, 26) + '...';
  }
  ctx.fillText(renderedText, 0, bubbleY + bubbleHeight / 2);
}
