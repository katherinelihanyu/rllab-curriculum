#!/Users/dementrock/anaconda/envs/rllab3/bin/python
import json
import logging
import multiprocessing
import re
import sys

import click
import subprocess

import redis

from sandbox.rocky.cirrascale import cirra_config
from sandbox.rocky.cirrascale.launch_job import FORBIDDEN

DEBUG_LOGGING_MAP = {
    0: logging.CRITICAL,
    1: logging.WARNING,
    2: logging.INFO,
    3: logging.DEBUG
}


@click.group()
@click.option('--verbose', '-v',
              help="Sets the debug noise level, specify multiple times "
                   "for more verbosity.",
              type=click.IntRange(0, 3, clamp=True),
              count=True)
@click.pass_context
def cli(ctx, verbose):
    logger_handler = logging.StreamHandler(sys.stderr)
    logger_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(logger_handler)
    logging.getLogger().setLevel(DEBUG_LOGGING_MAP.get(verbose, logging.DEBUG))


def _get_gpu_type(host):
    try:
        result = subprocess.check_output([
            "ssh",
            "-oStrictHostKeyChecking=no",
            "-oConnectTimeout=10",
            "rocky@" + host, "nvidia-smi -L"
        ])
    except Exception as e:
        print("Error while probing %s" % host)
        return (host, None)
    result = result.decode()
    if "GeForce GTX TITAN X" in result:
        print("%s identified as TitanX Maxwell" % host)
        return (host, "maxwell")
    elif "TITAN X (Pascal)" in result:
        print("%s identified as TitanX Pascal" % host)
        return (host, "pascal")
    else:
        print(result)
        return (host, None)


@cli.command()
def update_directory():
    hosts = ["%d.cirrascale.sci.openai.org" % idx for idx in range(1, 100)]
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)
    with multiprocessing.Pool(processes=100) as pool:
        print("Probing status...")
        results = pool.map(_get_gpu_type, hosts)
        results = dict([(k, v) for k, v in results if v is not None])
        print("Updating redis...")
        redis_cli.set(cirra_config.DIRECTORY_KEY, json.dumps(results))
        print("Updated")


def _probe_host(host):
    try:
        pids = subprocess.check_output([
            "ssh",
            "-oStrictHostKeyChecking=no",
            "-oConnectTimeout=10",
            "rocky@" + host,
            "nvidia-smi --format=csv,noheader --query-compute-apps=pid",
        ])
        pids = pids.decode().strip().split('\n')
        if len(pids) == 0:
            return []
        gpus = subprocess.check_output([
            "ssh",
            "-oStrictHostKeyChecking=no",
            "-oConnectTimeout=10",
            "rocky@" + host,
            "nvidia-smi --format=csv,noheader --query-gpu=index"
        ])
        gpus = gpus.decode().strip().split('\n')
        if len(gpus) == 0:
            return []
        processes = subprocess.check_output([
            "ssh",
            "-oStrictHostKeyChecking=no",
            "-oConnectTimeout=10",
            "rocky@" + host,
            "ps aux | grep -e '%s'" % '\|'.join(pids)
        ])
        lines = [l for l in processes.decode().split('\n') if 'exp_name' in l and not 'peter' in l]

        ret = []
        for line in lines:
            words = line.split()
            idx = words.index('--exp_name')
            exp_name = words[idx + 1]
            process = words[1]
            gpu = gpus[pids.index(process)]
            ret.append((host, gpu, exp_name))
        print("Finished probing %s" % host)
        return ret
    except Exception as e:
        print("Error while probing %s" % host)
        print(e)
        return []


def _probe_stats(host):
    try:
        disk_usage = subprocess.check_output([
            "ssh",
            "-oStrictHostKeyChecking=no",
            "-oConnectTimeout=10",
            "rocky@" + host,
            "df -h",
        ])
        lines = [x.split() for x in disk_usage.decode().split('\n')][:-1]
        avail_size = [l for l in lines if l[-1] == '/'][0][-3]
        print("Finished probing %s" % host)
        return dict(
            host=host,
            status="Available local disk: {}".format(avail_size)
        )
    except Exception as e:
        print("Error while probing %s" % host)
        print(e)
        return dict(
            host=host,
            status="error",
        )


@cli.command()
def probe():
    from sandbox.rocky.cirrascale.launch_job import get_directory
    dir = get_directory()
    hosts = dir.keys()
    with multiprocessing.Pool(processes=100) as pool:
        print("Probing host status...")
        results = pool.map(_probe_host, hosts)
        for host, gpu, exp_name in sorted(sum(results, []), key=lambda x: x[::-1]):
            print('%s running on %s:%s' % (exp_name, host, gpu))
        print("Saving result to redis...")
        redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)
        to_set = dict()
        for host, gpu, exp_name in sorted(sum(results, []), key=lambda x: x[::-1]):
            to_set["job/%s" % exp_name] = json.dumps(dict(
                job_id=exp_name,
                gpu_host=host,
                gpu_index=gpu
            ))
        if len(to_set) > 0:
            redis_cli.mset(to_set)


@cli.command()
def stats():
    from sandbox.rocky.cirrascale import client
    from sandbox.rocky.cirrascale.launch_job import get_directory
    dir = get_directory()
    gpus = client.get_gpu_status()
    n_pascals = 0
    n_free_pascals = 0
    n_maxwells = 0
    n_free_maxwells = 0
    for host, gpus in gpus.items():
        if int(host.split('.')[0]) not in FORBIDDEN:
            if host in dir and dir[host] == "pascal":
                n_pascals += len(gpus)
                n_free_pascals += len([g for g in gpus if g.available])
            elif host in dir and dir[host] == "maxwell":
                n_maxwells += len(gpus)
                n_free_maxwells += len([g for g in gpus if g.available])
            else:
                pass
    print("#Pascal GPU: %d" % n_pascals)
    print("#Free Pascal GPU: %d" % n_free_pascals)
    print("#Maxwell GPU: %d" % n_maxwells)
    print("#Free Maxwell GPU: %d" % n_free_maxwells)
    # print("Probing instances for remaining disk space...")
    # hosts = dir.keys()
    # # for host in hosts:
    # #     _probe_stats(host)
    # with multiprocessing.Pool(processes=100) as pool:
    #     print("Probing host stats...")
    #     results = pool.map(_probe_stats, hosts)
    #     results = sorted(results, key=lambda x: int(x['host'].split('.')[0]))
    #     for result in results:
    #         host = result['host']
    #         status = result['status']
    #         print("{}: {}".format(host, status))

@cli.command()
@click.option('--all', '-a', default=False, help='show status of each job')
def jobs(all):
    import redis
    import json
    from sandbox.rocky.cirrascale import cirra_config
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)
    jobs = redis_cli.keys("job/*")
    if len(jobs) == 0:
        print("No jobs currently running")
    else:
        job_dicts = [json.loads(x.decode()) for x in redis_cli.mget(jobs)]
        job_dicts = sorted(job_dicts, key=lambda x: x["job_id"])

        for job in job_dicts:
            print("%s running on %s:%s" % (job["job_id"], job["gpu_host"], job["gpu_index"]))


@cli.command()
@click.argument('job_id')
@click.option('--force', '-f', default=False, help='force removal of the job from redis')
def kill(job_id, force):
    _kill_job(("job/" + job_id, force))


@cli.command()
@click.argument('job_id')
def ssh(job_id):
    import redis
    import json
    import subprocess
    import os
    from sandbox.rocky.cirrascale import cirra_config
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)

    content = redis_cli.get("job/%s" % job_id)
    job = json.loads(content.decode())
    print(job)

    command = "ssh -t rocky@{gpu_host} 'cd /local_home/rocky/rllab-workdir/{job_id} && exec bash -l'".format(
        gpu_host=job['gpu_host'], job_id=job_id)
    print(command)
    os.system(command)



@cli.command()
@click.argument('job_id')
@click.option('--deterministic', '-d', default=False, help='run policy in deterministic mode')
def sim_policy(job_id, deterministic):
    import redis
    import json
    import subprocess
    import os
    from sandbox.rocky.cirrascale import cirra_config
    from rllab import config
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)

    content = redis_cli.get("job/%s" % job_id)
    if content is None:
        result = search_job(job_id)
    job = json.loads(content.decode())
    print(job)

    file_location = subprocess.check_output([
        "ssh",
        "rocky@{gpu_host}".format(gpu_host=job['gpu_host']),
        "find /local_home/rocky/rllab-workdir/{job_id}/data/local -name *.pkl".format(job_id=job_id)
    ]).decode().split("\n")[0]
    subprocess.check_call([
        "ssh",
        "rocky@{gpu_host}".format(gpu_host=job['gpu_host']),
        "cp {file} /tmp/params.pkl".format(file=file_location)
    ])
    subprocess.check_call([
        "scp",
        "rocky@{gpu_host}:/tmp/params.pkl".format(gpu_host=job['gpu_host']),
        "/tmp/params.pkl"
    ])

    if "conopt" in file_location or "analogy" in file_location:
        script = "sandbox/rocky/analogy/scripts/sim_policy.py"
    else:
        script = "scripts/sim_policy.py"
    command = [
        "python",
        os.path.join(config.PROJECT_PATH, script),
        "/tmp/params.pkl"
    ]
    if deterministic:
        command += ["--deterministic"]
    subprocess.check_call(command)


def _kill_job(args):
    job_id, force = args
    try:
        ret = ""
        redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)
        content = redis_cli.get(job_id)
        job = json.loads(content.decode())
        print(job)

        assert len(job['job_id']) > 5

        command = [
            "ssh",
            "rocky@%s" % job['gpu_host'],
            "sudo kill -9 $(ps aux | grep %s | awk '{print $2}')" % job['job_id'],
        ]

        print(" ".join(command))

        ret = subprocess.check_output(command)
    except Exception as e:
        print(e)
        print(len(ret))
        if not force:
            return

    redis_cli.delete(job_id)
    print("Job %s deleted" % job_id)


@cli.command()
@click.option('--force', '-f', default=False, help='force removal of the job from redis')
def kill_all(force):
    import redis
    from sandbox.rocky.cirrascale import cirra_config
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)

    jobs = redis_cli.keys("job/*")  # % job_id)

    with multiprocessing.Pool(100) as pool:
        pool.map(_kill_job, zip(jobs, [force] * len(jobs)))


@cli.command()
@click.argument('pattern')
@click.option('--force', '-f', default=False, help='force removal of the job from redis')
def kill_f(pattern, force):
    import redis
    from sandbox.rocky.cirrascale import cirra_config
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)

    jobs = redis_cli.keys("job/*")  # % job_id)

    to_kill = []
    for job_id in jobs:
        if pattern in job_id.decode():
            to_kill.append((job_id, force))

    with multiprocessing.Pool(100) as pool:
        pool.map(_kill_job, to_kill)


@cli.command()
@click.argument('pattern')
@click.option('--force', '-f', default=False, help='force removal of the job from redis')
def kill_variant(pattern, force):
    import redis
    from sandbox.rocky.cirrascale import cirra_config
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)

    jobs = redis_cli.keys("job/*")  # % job_id)

    to_kill = []
    for job_id in jobs:
        if pattern in job_id.decode():
            to_kill.append((job_id, force))

    with multiprocessing.Pool(100) as pool:
        pool.map(_kill_job, to_kill)


@cli.command()
@click.argument('job_id')
@click.option('--lines', '-n', default=30, help='output the last K lines of the log')
def status(job_id, lines):
    import subprocess
    import redis
    import json
    from sandbox.rocky.cirrascale import cirra_config
    redis_cli = redis.StrictRedis(host=cirra_config.REDIS_HOST)
    content = redis_cli.get("job/%s" % job_id)
    if content is None:
        print("No job with name %s exists" % job_id)
    else:
        job = json.loads(content.decode())
        print(job)

        command = [
            "ssh",
            "rocky@%s" % job['gpu_host'],
            'tail -n %d /local_home/rocky/rllab-workdir/%s/user_data.log' % (lines, job_id)
        ]

        print(command)

        try:
            print(subprocess.check_output(command).decode())
        except Exception as e:
            print(e)


if __name__ == '__main__':
    cli()