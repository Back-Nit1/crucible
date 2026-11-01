import { render, screen } from "@testing-library/react";
import { getSample } from "@/lib/api/samples";
import { episodeDetailSchema } from "@/lib/api/schemas";
import { EpisodeDetailView } from "./episode-detail";
import { toEpisodeQuery } from "./episode-grid";

describe("episode explorer", () => {
  it("maps filters and AG Grid sort into the supported server query", () => {
    expect(
      toEpisodeQuery(
        {
          generation_id: "gen-1",
          agent_id: "",
          split: "test",
          category: "Electronics",
          killed: "true",
          kill_rule_id: "K001_HALLUCINATED_PRODUCT",
          min_fitness: "0.2",
          max_fitness: "0.8",
        },
        { startRow: 50, endRow: 75, sortModel: [{ colId: "category", sort: "asc" }] },
      ),
    ).toEqual({
      generation_id: "gen-1",
      agent_id: undefined,
      split: "test",
      category: "Electronics",
      killed: true,
      kill_rule_id: "K001_HALLUCINATED_PRODUCT",
      min_fitness: 0.2,
      max_fitness: 0.8,
      sort: "category",
      offset: 50,
      limit: 25,
    });
  });

  it("makes scripted provenance and kill evidence explicit", () => {
    const episode = episodeDetailSchema.parse(getSample("world_episode_detail_killed").body);
    render(<EpisodeDetailView episode={episode} sample />);

    expect(screen.getByText(/reference-answer-driven scripted episode/i)).toBeVisible();
    expect(screen.getAllByText("K008_REVIEW_GAMING").length).toBeGreaterThan(0);
    expect(screen.getByText(/raw output hash/i).parentElement).toHaveTextContent("Not published");
  });
});
