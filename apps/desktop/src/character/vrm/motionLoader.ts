/** VRMA asset loader: retarget downloaded humanoid rotations and expression curves without authoring gestures. */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";

/** 与渲染无关的动作轨道中间表示（骨骼名即 VRM humanoid 名） */
export interface VrmTracks {
  duration: number;
  rotation: Map<VRMHumanBoneName, THREE.QuaternionKeyframeTrack>;
  /** hips 模型空间平移（米；消费端按目标髋高等比缩放） */
  hipsTranslation: THREE.VectorKeyframeTrack | null;
  /** 表情权重轨道（preset/custom 名 → weight 曲线，0..1） */
  expressions: Map<string, THREE.NumberKeyframeTrack>;
}

/** VRMC_vrm_animation 扩展的 JSON 形状（子集） */
interface VrmaExtension {
  humanoid?: { humanBones?: Record<string, { node?: number }> };
  expressions?: {
    preset?: Record<string, { node?: number }>;
    custom?: Record<string, { node?: number }>;
  };
}

/**
 * 从已加载的 GLTF 提取 VRMA 轨道。
 * nodes 为 parser.getDependencies("node") 的结果（index 对齐 glTF nodes 数组）；
 * 读取前须已 updateWorldMatrix（rest 姿态，VRMA 节点为 T-pose 平铺）。
 */
function parseVrma(
  gltf: { scene: THREE.Object3D; animations: THREE.AnimationClip[]; nodes: THREE.Object3D[] },
  ext: VrmaExtension,
  channels: readonly { target?: { node?: number; path?: string } }[],
): VrmTracks | null {
  if (!ext.humanoid?.humanBones) return null;
  const boneByIndex = new Map<number, VRMHumanBoneName>();
  for (const [name, bone] of Object.entries(ext.humanoid.humanBones)) {
    if (bone?.node != null) boneByIndex.set(bone.node, name as VRMHumanBoneName);
  }
  const expressionByIndex = new Map<number, string>();
  for (const group of [ext.expressions?.preset, ext.expressions?.custom]) {
    for (const [name, entry] of Object.entries(group ?? {})) {
      if (entry?.node != null) expressionByIndex.set(entry.node, name);
    }
  }

  const clip = gltf.animations[0];
  if (!clip) return null;
  const result: VrmTracks = {
    duration: clip.duration,
    rotation: new Map(),
    hipsTranslation: null,
    expressions: new Map(),
  };

  channels.forEach((channel, iChannel) => {
    const nodeIndex = channel.target?.node;
    const path = channel.target?.path;
    const track = clip.tracks[iChannel];
    if (nodeIndex == null || !track) return;

    const bone = boneByIndex.get(nodeIndex);
    if (bone) {
      const node = gltf.nodes[nodeIndex];
      if (!node) return;
      if (path === "rotation" && track instanceof THREE.QuaternionKeyframeTrack) {
        const restWorld = node.getWorldQuaternion(new THREE.Quaternion()).invert();
        const parentWorld = (node.parent ?? node).getWorldQuaternion(new THREE.Quaternion());
        const values = track.values.slice();
        const q = new THREE.Quaternion();
        for (let i = 0; i < values.length; i += 4) {
          q.fromArray(values, i).premultiply(parentWorld).multiply(restWorld).toArray(values, i);
        }
        result.rotation.set(
          bone,
          new THREE.QuaternionKeyframeTrack(`${bone}.quaternion`, track.times, values),
        );
      } else if (
        path === "translation" &&
        bone === "hips" &&
        track instanceof THREE.VectorKeyframeTrack
      ) {
        // VRMA hips 平移为模型空间（米）；平铺节点父世界矩阵 ≈ 单位，原值直通
        result.hipsTranslation = track.clone();
      }
      return;
    }

    const expressionName = expressionByIndex.get(nodeIndex);
    if (expressionName && path === "translation" && track instanceof THREE.VectorKeyframeTrack) {
      const values = new Array<number>(track.values.length / 3);
      for (let i = 0; i < values.length; i += 1) values[i] = track.values[3 * i];
      result.expressions.set(
        expressionName,
        new THREE.NumberKeyframeTrack(`${expressionName}.weight`, track.times, values),
      );
    }
  });

  return result;
}

interface LoadedGltf {
  scene: THREE.Object3D;
  animations: THREE.AnimationClip[];
  parser: {
    json: {
      extensions?: Record<string, unknown>;
      animations?: { channels?: unknown }[] | undefined;
    };
  };
}

/** 加载含 VRMC_vrm_animation 扩展的文件，提取原始 VRMA 轨道。 */
export async function loadVrmaTracks(url: string): Promise<VrmTracks> {
  const gltf = (await new GLTFLoader().loadAsync(url)) as LoadedGltf;
  const ext = gltf.parser.json.extensions?.["VRMC_vrm_animation"] as VrmaExtension | undefined;
  if (ext) {
    // node 依赖按 glTF index 对齐；updateWorldMatrix 后读 rest 世界矩阵
    const nodes = (await (
      gltf.parser as unknown as {
        getDependencies: (type: string) => Promise<THREE.Object3D[]>;
      }
    ).getDependencies("node")) as THREE.Object3D[];
    gltf.scene.updateWorldMatrix(false, true);
    const channels = (gltf.parser.json.animations?.[0]?.channels ?? []) as {
      target?: { node?: number; path?: string };
    }[];
    const tracks = parseVrma(
      { scene: gltf.scene, animations: gltf.animations, nodes },
      ext,
      channels,
    );
    if (!tracks || tracks.rotation.size === 0) throw new Error("VRMA 扩展存在但无可用轨道");
    return tracks;
  }
  throw new Error("文件不包含有效的 VRM Animation（VRMC_vrm_animation）动作数据");
}

/** Load one downloaded VRMA without changing its keyframes or expression curves. */
export function loadMotionTracks(url: string): Promise<VrmTracks> {
  const clean = url.split("?")[0].toLowerCase();
  if (!clean.endsWith(".vrma")) return Promise.reject(new Error("角色动作仅支持 .vrma 文件"));
  return loadVrmaTracks(url);
}

/** Validate and measure an import before storing it; release its temporary URL even on failure. */
export async function loadVrmaFile(file: File): Promise<VrmTracks> {
  if (!file.name.toLowerCase().endsWith(".vrma")) throw new Error("请选择 .vrma 文件");
  const url = URL.createObjectURL(file);
  try {
    const tracks = await loadVrmaTracks(url);
    if (!Number.isFinite(tracks.duration) || tracks.duration < 0.1 || tracks.duration > 60) {
      throw new Error("动作时长须在 0.1–60 秒之间");
    }
    return tracks;
  } finally {
    URL.revokeObjectURL(url);
  }
}
