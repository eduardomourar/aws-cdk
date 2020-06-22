import json
import logging
import os
import subprocess

from distutils.util import strtobool

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# these are coming from the kubectl layer
os.environ['PATH'] = '/opt/helm:/opt/awscli:' + os.environ['PATH']

outdir = os.environ.get('TEST_OUTDIR', '/tmp')
kubeconfig = os.path.join(outdir, 'kubeconfig')

def decode_boolean(value):
    """Decodes encoded true/false value"""
    if isinstance(value, bool):
        return value
    elif isinstance(value, str) or isinstance(value, int):
        if value == 'TRUE:BOOLEAN':
            return True
        elif value == 'FALSE:BOOLEAN':
            return False
        else:
            # Needed for backward compatilibity because previous state
            # will have a string value ('true' or 'false')
            return bool(strtobool(value))
    return None

def helm_handler(event, context):
    logger.info(json.dumps(event))

    request_type = event['RequestType']
    props = event['ResourceProperties']

    # resource properties
    cluster_name = props['ClusterName']
    role_arn     = props['RoleArn']
    release      = props['Release']
    chart        = props['Chart']
    version      = props.get('Version', None)
    wait         = decode_boolean(props.get('Wait', False))
    timeout      = props.get('Timeout', None)
    namespace    = props.get('Namespace', None)
    repository   = props.get('Repository', None)
    values_text  = props.get('Values', None)

    # "log in" to the cluster
    subprocess.check_call([ 'aws', 'eks', 'update-kubeconfig',
        '--role-arn', role_arn,
        '--name', cluster_name,
        '--kubeconfig', kubeconfig
    ])

    # Write out the values to a file and include them with the install and upgrade
    values_file = None
    if not request_type == "Delete" and not values_text is None:
        values = json.loads(values_text)
        values_file = os.path.join(outdir, 'values.yaml')
        with open(values_file, "w") as f:
            f.write(json.dumps(values, indent=2))

    if request_type == 'Create' or request_type == 'Update':
        helm('upgrade', release, chart, repository, values_file, namespace, version, wait, timeout)
    elif request_type == "Delete":
        try:
            helm('uninstall', release, namespace=namespace, timeout=timeout)
        except Exception as e:
            logger.info("delete error: %s" % e)

def helm(verb, release, chart = None, repo = None, file = None, namespace = None, version = None, wait = False, timeout = None):
    import subprocess

    cmnd = ['helm', verb, release]
    if not chart is None:
        cmnd.append(chart)
    if verb == 'upgrade':
        cmnd.append('--install')
    if not repo is None:
        cmnd.extend(['--repo', repo])
    if not file is None:
        cmnd.extend(['--values', file])
    if not version is None:
        cmnd.extend(['--version', version])
    if not namespace is None:
        cmnd.extend(['--namespace', namespace])
    if wait:
        cmnd.append('--wait')
    if not timeout is None:
        cmnd.extend(['--timeout', timeout])  
    cmnd.extend(['--kubeconfig', kubeconfig])

    retry = 3
    while retry > 0:
        try:
            output = subprocess.check_output(cmnd, stderr=subprocess.STDOUT, cwd=outdir)
            logger.info(output)
            return
        except subprocess.CalledProcessError as exc:
            output = exc.output
            if b'Broken pipe' in output:
                logger.info("Broken pipe, retries left: %s" % retry)
                retry = retry - 1
            else:
                raise Exception(output)
