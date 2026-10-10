import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";
import { createVrmWorld } from "./world";

const mocks = vi.hoisted(() => ({ resize: null as (() => void) | null }));
vi.mock("three", async (importOriginal) => {
  class Canvas extends EventTarget {
    style: Record<string, string> = {};
    clientHeight = 340;
    root = new EventTarget();
    getRootNode() {
      return this.root;
    }
    setAttribute() {}
    setPointerCapture() {}
    releasePointerCapture() {}
    remove() {}
  }
  return {
    ...(await importOriginal<typeof import("three")>()),
    WebGLRenderer: class {
      domElement = new Canvas();
      setClearColor() {}
      setPixelRatio() {}
      setSize() {}
      dispose() {}
    },
  };
});

beforeEach(() => {
  vi.stubGlobal("window", { devicePixelRatio: 1 });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        mocks.resize = callback;
      }
      observe() {}
      disconnect() {}
    },
  );
});
afterEach(() => vi.unstubAllGlobals());

function preview() {
  const host = { clientWidth: 500, clientHeight: 340, appendChild() {} };
  const world = createVrmWorld(host as unknown as HTMLElement, { view: "preview" });
  world.frame(
    new THREE.Box3(new THREE.Vector3(-0.325, 0, -0.1), new THREE.Vector3(0.325, 1.7, 0.1)),
  );
  const pointer = (type: string, x: number) => {
    const event = new Event(type);
    Object.assign(event, {
      pointerId: 1,
      pointerType: "mouse",
      button: 0,
      clientX: x,
      clientY: 170,
    });
    world.renderer.domElement.dispatchEvent(event);
  };
  const drag = () => {
    pointer("pointerdown", 250);
    pointer("pointermove", 350);
    pointer("pointerup", 350);
    for (let i = 0; i < 120; i++) world.updateView();
  };
  return { world, host, drag, pointer };
}

describe("VRM preview camera", () => {
  it("centers the full character and fills most of the enlarged preview", () => {
    const { world, host } = preview();
    world.camera.updateMatrixWorld(true);
    const top = new THREE.Vector3(0, 1.7, 0).project(world.camera);
    const bottom = new THREE.Vector3(0, 0, 0).project(world.camera);
    expect(top.y).toBeLessThan(1);
    expect(bottom.y).toBeGreaterThan(-1);
    expect(top.y + bottom.y).toBeCloseTo(0);
    expect(((top.y - bottom.y) / 2) * host.clientHeight).toBeGreaterThan(host.clientHeight * 0.8);
    world.dispose();
  });

  it("orbits with real pointer events, preserves the view on resize and resets to the front", () => {
    const { world, host, drag } = preview();
    const front = world.camera.position.clone();
    drag();
    expect(world.camera.position.distanceTo(front)).toBeGreaterThan(5);
    const turned = world.camera.position.clone();
    host.clientWidth = 420;
    mocks.resize?.();
    expect(world.camera.position.distanceTo(turned)).toBeLessThan(0.001);
    expect(
      (world.camera.right - world.camera.left) / (world.camera.top - world.camera.bottom),
    ).toBeCloseTo(420 / 340);
    world.resetView();
    expect(world.camera.position.distanceTo(front)).toBeLessThan(0.01);
    world.dispose();
  });

  it("removes pointer controls when the preview is disposed", () => {
    const { world, drag } = preview();
    const front = world.camera.position.clone();
    world.dispose();
    drag();
    expect(world.camera.position.distanceTo(front)).toBeLessThan(0.001);
  });

  it("resets immediately after dragging without residual camera drift", () => {
    const { world, pointer } = preview();
    const front = world.camera.position.clone();
    pointer("pointerdown", 250);
    pointer("pointermove", 350);
    pointer("pointerup", 350);
    world.resetView();
    for (let i = 0; i < 120; i++) world.updateView();
    expect(world.camera.position.distanceTo(front)).toBeLessThan(0.001);
    world.dispose();
  });
});
