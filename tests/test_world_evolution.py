from decimal import Decimal

from world.evolution import (
    DeterministicMutationProposer, GenerationCheckpoint, breed_generation, genome_hash,
    initialize_population, select_survivors,
)


def test_seeded_population_selection_and_hashes_are_stable():
    first = initialize_population(8, 41)
    second = initialize_population(8, 41)
    assert first == second
    assert [genome_hash(item) for item in first] == [genome_hash(item) for item in second]
    fitness = {genome.id: Decimal(index) for index, genome in enumerate(first)}
    survivors = select_survivors(first, fitness, {first[-1].id})
    assert first[-1] not in survivors
    assert survivors == select_survivors(first, fitness, {first[-1].id})


def test_killed_agents_cannot_reproduce_and_survivors_are_elites():
    population = initialize_population(8, 7)
    fitness = {genome.id: Decimal(index) for index, genome in enumerate(population)}
    killed = {population[-1].id}
    survivors = select_survivors(population, fitness, killed)
    children = breed_generation(survivors, fitness, 8, 1, 99, DeterministicMutationProposer())
    assert children[:len(survivors)] == survivors
    assert all(child.parent_id in {item.id for item in survivors} for child in children[len(survivors):])
    assert all(child.parent_id not in killed for child in children)


def test_mutations_stay_in_ranges_and_parent_references_exist():
    population = initialize_population(4, 2)
    fitness = {genome.id: Decimal(index) for index, genome in enumerate(population)}
    next_population = breed_generation(population[:2], fitness, 10, 2, 5, DeterministicMutationProposer())
    for genome in next_population:
        assert Decimal(0) <= genome.temperature <= Decimal(2)
        assert 1 <= genome.search.minimum_candidates <= 10
        assert Decimal(0) <= genome.reviews.critical_fraction <= Decimal(1)


def test_checkpoint_resume_is_idempotent_and_hash_stable():
    population = initialize_population(2, 3)
    completed = f"{population[0].id}:task-a"
    checkpoint = GenerationCheckpoint(generation_id="gen-1", seed=3, genomes=population,
        task_ids=("task-a", "task-b"), completed_episode_keys=(completed,))
    assert checkpoint.remaining_episode_keys() == (
        f"{population[0].id}:task-b", f"{population[1].id}:task-a", f"{population[1].id}:task-b")
    assert checkpoint.content_hash() == GenerationCheckpoint.model_validate_json(
        checkpoint.model_dump_json()).content_hash()
