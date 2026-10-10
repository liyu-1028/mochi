/**
 * PROTOTYPE — Mixamo 动作映射到 VRM normalized 骨架。
 * Adapted from pixiv/three-vrm humanoidAnimation example (MIT).
 * Copyright (c) 2019 pixiv Inc. — 完整许可见 assets/prototypes/vrm-dance/README.md。
 */
import * as THREE from "three";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { type VRM, type VRMHumanBoneName } from "@pixiv/three-vrm";

const rigMap: Record<string, VRMHumanBoneName> = {
  Hips: "hips",
  Spine: "spine",
  Spine1: "chest",
  Spine2: "upperChest",
  Neck: "neck",
  Head: "head",
};
for (const side of ["Left", "Right"] as const) {
  const prefix = side === "Left" ? "left" : "right";
  const limbs = {
    Shoulder: "Shoulder",
    Arm: "UpperArm",
    ForeArm: "LowerArm",
    Hand: "Hand",
    UpLeg: "UpperLeg",
    Leg: "LowerLeg",
    Foot: "Foot",
    ToeBase: "Toes",
  } as const;
  for (const [source, target] of Object.entries(limbs)) {
    rigMap[`${side}${source}`] = `${prefix}${target}` as VRMHumanBoneName;
  }
  for (const finger of ["Thumb", "Index", "Middle", "Ring", "Pinky"] as const) {
    const name = finger === "Pinky" ? "Little" : finger;
    const joints =
      finger === "Thumb"
        ? ["Metacarpal", "Proximal", "Distal"]
        : ["Proximal", "Intermediate", "Distal"];
    joints.forEach((joint, index) => {
      rigMap[`${side}Hand${finger}${index + 1}`] = `${prefix}${name}${joint}` as VRMHumanBoneName;
    });
  }
}

export async function loadDance(vrm: VRM): Promise<THREE.AnimationClip> {
  const asset = await new FBXLoader().loadAsync("/prototype-assets/samba.fbx");
  try {
    const clip = asset.animations[0];
    if (!clip) throw new Error("舞蹈文件没有动画轨道");
    asset.updateMatrixWorld(true);
    // FBXLoader 版本和导出器可能保留或移除冒号。
    const sourceHips =
      asset.getObjectByName("mixamorigHips") ?? asset.getObjectByName("mixamorig:Hips");
    const targetHeight = vrm.humanoid.normalizedRestPose.hips?.position?.[1];
    if (!sourceHips || !targetHeight || !sourceHips.position.y) throw new Error("无法定位人形髋骨");
    const scale = targetHeight / sourceHips.position.y;
    const tracks: THREE.KeyframeTrack[] = [];
    for (const track of clip.tracks) {
      const [sourceName, property] = track.name.split(".");
      const bone = rigMap[sourceName.replace(/^mixamorig:?/, "")];
      if (!bone) continue;
      const target = vrm.humanoid.getNormalizedBoneNode(bone);
      const source = asset.getObjectByName(sourceName);
      if (!target || !source?.parent) continue;
      if (track instanceof THREE.QuaternionKeyframeTrack) {
        const inverseRest = source.getWorldQuaternion(new THREE.Quaternion()).invert();
        const parentRest = source.parent.getWorldQuaternion(new THREE.Quaternion());
        const values = track.values.slice();
        const rotation = new THREE.Quaternion();
        for (let i = 0; i < values.length; i += 4) {
          rotation
            .fromArray(values, i)
            .premultiply(parentRest)
            .multiply(inverseRest)
            .toArray(values, i);
        }
        tracks.push(
          new THREE.QuaternionKeyframeTrack(`${target.name}.${property}`, track.times, values),
        );
      } else if (
        track instanceof THREE.VectorKeyframeTrack &&
        bone === "hips" &&
        property === "position"
      ) {
        // 保留原始脚步位移与上下起伏，只平移水平起点到舞台中心。
        const values = track.values.map(
          (v, i) => (v - (i % 3 === 1 ? 0 : track.values[i % 3])) * scale,
        );
        tracks.push(new THREE.VectorKeyframeTrack(`${target.name}.position`, track.times, values));
      }
    }
    if (tracks.length < 15) throw new Error(`骨骼映射不足：只有 ${tracks.length} 条轨道`);
    return new THREE.AnimationClip("Samba Dancing", clip.duration, tracks);
  } finally {
    // FBX 只用于读取动作；不把原始角色网格留在内存中。
    asset.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        for (const value of Object.values(material))
          if (value instanceof THREE.Texture) value.dispose();
        material.dispose();
      }
    });
  }
}
