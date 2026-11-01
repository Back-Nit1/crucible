"""Runs INSIDE the WebShop interpreter (Python 3.8 + the benchmark's requirements); stdlib + WebShop only.

Protocol: one JSON object per line on stdin, one JSON reply per line on stdout.
  {"cmd": "reset", "session": 7}  -> {"ok": true, "observation", "instruction", "available": {...}}
  {"cmd": "step", "action": "search[red shoes]"} -> {"ok": true, "observation", "reward", "done", "available"}
Environment is constructed exactly as the WebShop README documents: gym.make('WebAgentTextEnv-v0', observation_mode='text',
num_products=N). WebShop prints to stdout while loading, so the protocol channel is the ORIGINAL stdout and everything
else is redirected to stderr."""
import json
import os
import sys


def main(argv):
    channel, sys.stdout = sys.stdout, sys.stderr
    sys.path.insert(0, os.getcwd())  # the WebShop clone (cwd) holds web_agent_site; a script's own dir is on sys.path instead
    import gym
    import web_agent_site.envs  # noqa: F401  (registers WebAgentTextEnv-v0)

    num_products = None if len(argv) < 2 or argv[1] == "all" else int(argv[1])
    env = gym.make("WebAgentTextEnv-v0", observation_mode="text", num_products=num_products)
    env = getattr(env, "unwrapped", env)

    def reply(**body):
        channel.write(json.dumps(body) + "\n")
        channel.flush()

    for line in sys.stdin:
        try:
            msg = json.loads(line)
            if msg["cmd"] == "reset":
                observation, _ = env.reset(session=int(msg["session"]))
                reply(ok=True, observation=observation, instruction=env.instruction_text, available=env.get_available_actions())
            elif msg["cmd"] == "step":
                observation, reward, done, _ = env.step(msg["action"])
                reply(ok=True, observation=observation, reward=float(reward), done=bool(done), available=env.get_available_actions())
            elif msg["cmd"] == "close":
                reply(ok=True)
                return 0
            else:
                reply(ok=False, error="unknown command")
        except Exception as exc:  # report, never die silently: the adapter records it as a backend error
            reply(ok=False, error="%s: %s" % (type(exc).__name__, exc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
