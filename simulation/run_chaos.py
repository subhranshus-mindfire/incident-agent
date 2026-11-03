import argparse
import asyncio
import logging

from simulation.chaos_client import ChaosClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("simulation.runner")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Live Incident Chaos Simulation Runner")
    parser.add_argument(
        "--scenario",
        choices=[
            "deadlock",
            "bad-deployment",
            "cpu-burn",
            "clear",
            "traffic",
            "rollback",
            "health",
        ],
        default="deadlock",
        help="Chaos scenario or action to trigger",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8080",
        help="Target base URL of payment-api",
    )
    parser.add_argument(
        "--traffic-count",
        type=int,
        default=15,
        help="Number of requests to generate",
    )

    args = parser.parse_args()
    client = ChaosClient(base_url=args.url)

    logger.info(f"Targeting payment-api at {args.url} with action: {args.scenario}")

    if args.scenario == "health":
        res = await client.get_health()
        logger.info(f"Health status: {res}")
    elif args.scenario == "deadlock":
        await client.inject_deadlock()
        logger.info("Generating traffic to stream errors into Loki and Prometheus...")
        codes = await client.generate_traffic(count=args.traffic_count)
        logger.info(f"Traffic results: {codes.count(500)} 500s, {codes.count(200)} 200s")
    elif args.scenario == "bad-deployment":
        await client.inject_bad_deployment()
        logger.info("Generating traffic to stream errors into Loki and Prometheus...")
        codes = await client.generate_traffic(count=args.traffic_count)
        logger.info(f"Traffic results: {codes.count(500)} 500s, {codes.count(200)} 200s")
    elif args.scenario == "cpu-burn":
        await client.inject_cpu_burn()
        logger.info("CPU burn active. Generating requests under load...")
        codes = await client.generate_traffic(count=args.traffic_count)
        logger.info(f"Traffic results: {len(codes)} processed under load")
    elif args.scenario == "traffic":
        codes = await client.generate_traffic(count=args.traffic_count)
        logger.info(
            f"Generated {len(codes)} requests: {codes.count(200)} 200s, {codes.count(500)} 500s"
        )
    elif args.scenario == "rollback":
        res = await client.rollback()
        logger.info(f"Rollback result: {res}")
    elif args.scenario == "clear":
        res = await client.clear_chaos()
        logger.info(f"Clear result: {res}")


if __name__ == "__main__":
    asyncio.run(main())
