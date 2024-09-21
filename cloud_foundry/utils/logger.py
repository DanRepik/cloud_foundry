import logging
import os

# Configuring the logging module with basic settings, including format and log level,
# where the log level is obtained from the environment variable LOGGING_LEVEL
# with a default of DEBUG, and force=True to ensure the configuration is applied immediately.
logging.basicConfig(
    format="%(name)s:%(lineno)s - %(levelname)s - %(message)s",
    level=os.getenv("LOGGING_LEVEL", "DEBUG").upper(),
    force=True,
)

WARN = logging.WARN
INFO = logging.INFO
DEBUG = logging.DEBUG


def logger(name=None):
    """
    Function to create a logger with a specified name or default name.

    Parameters:
        name (str): Name of the logger. If not provided, the root logger is returned.

    Returns:
        logging.Logger: Logger object with the specified name or the root logger.

    """
    # Retrieving the logging level from the environment variable LOGGING_LEVEL
    # with a default of DEBUG, and converting it to uppercase
    loggingLevel = os.getenv("LOGGING_LEVEL", "DEBUG").upper()

    # Setting the logging level for the root logger to the obtained logging level
    logging.getLogger().setLevel(loggingLevel)

    # Returning a logger object with the specified name or the root logger
    return logging.getLogger(name)


def write_logging_file(file_name, content):
    """
    Function to write a given string to a file in the temp/logging folder.

    Parameters:
        file_name (str): Name of the file to write the content to.
        content (str): The string content to write to the file.

    """
    # Define the directory path
    dir_path = os.path.join("temp", "logging")

    # Ensure the directory exists
    os.makedirs(dir_path, exist_ok=True)

    # Define the file path
    file_path = os.path.join(dir_path, file_name)

    # Write the content to the file
    with open(file_path, "w") as file:
        file.write(content + "\n")
