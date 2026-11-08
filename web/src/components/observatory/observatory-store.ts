"use client";

import { create } from "zustand";

type ObservatoryState = {
  stepIndex: number;
  playing: boolean;
  speed: number;
  selectedProductId: string | null;
  selectedAgentId: string | null;
  selectedShopId: string | null;
  time: number; // replay clock, seconds
  focusWorld: number | null; // world index the camera is zoomed into
  setTime: (time: number) => void;
  setFocusWorld: (world: number | null) => void;
  setStep: (step: number) => void;
  setPlaying: (playing: boolean) => void;
  togglePlaying: () => void;
  setSpeed: (speed: number) => void;
  selectProduct: (id: string | null) => void;
  selectAgent: (id: string | null) => void;
  selectShop: (id: string | null) => void;
  reset: () => void;
};

export const useObservatoryStore = create<ObservatoryState>((set) => ({
  stepIndex: 0,
  playing: false,
  speed: 1,
  selectedProductId: null,
  selectedAgentId: null,
  selectedShopId: null,
  time: 0,
  focusWorld: null,
  setTime: (time) => set({ time }),
  setFocusWorld: (focusWorld) => set({ focusWorld }),
  setStep: (stepIndex) => set({ stepIndex }),
  setPlaying: (playing) => set({ playing }),
  togglePlaying: () => set((state) => ({ playing: !state.playing })),
  setSpeed: (speed) => set({ speed }),
  selectProduct: (selectedProductId) =>
    set(
      selectedProductId
        ? { selectedProductId, selectedAgentId: null, selectedShopId: null }
        : { selectedProductId },
    ),
  selectAgent: (selectedAgentId) =>
    set(
      selectedAgentId
        ? { selectedAgentId, selectedProductId: null, selectedShopId: null }
        : { selectedAgentId },
    ),
  selectShop: (selectedShopId) =>
    set(
      selectedShopId
        ? { selectedShopId, selectedAgentId: null, selectedProductId: null }
        : { selectedShopId },
    ),
  reset: () =>
    set({
      stepIndex: 0,
      playing: false,
      speed: 1,
      selectedProductId: null,
      selectedAgentId: null,
      selectedShopId: null,
      time: 0,
      focusWorld: null,
    }),
}));
