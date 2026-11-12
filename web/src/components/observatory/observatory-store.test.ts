import { useObservatoryStore } from "./observatory-store";

describe("observatory store", () => {
  it("tracks the replay clock and focused world, and reset clears them", () => {
    const s = useObservatoryStore.getState();
    s.setTime(12.5);
    s.setFocusWorld(3);
    expect(useObservatoryStore.getState()).toMatchObject({ time: 12.5, focusWorld: 3 });
    useObservatoryStore.getState().reset();
    expect(useObservatoryStore.getState()).toMatchObject({ time: 0, focusWorld: null });
  });
});
