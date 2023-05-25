# tbot-tradingboat

## An Overview of TBOT: Purpose and Architecture

### The Purpose of TBOT

The purpose of TBOT (TradingBoat) is to serve as a trading robot application that integrates with TradingView's strategy or indicator tools and Interactive Brokers' trading platform. TBOT acts as the control center within the broader TradingBoat platform, decoding alert messages received from TradingView and placing corresponding orders with Interactive Brokers.

Here are the key aspects of TBOT's purpose and functionality:

- **Integration with TradingView:** TBOT receives alert messages containing trading strategies or indicators from TradingView. These messages are sent via Redis Pub/Sub or Redis Stream, and TBOT decodes them in real-time.

- **Interactive Brokers integration:** TBOT uses the ib_insync API to interact with Interactive Brokers' trading platform. It establishes a connection with Interactive Brokers to place orders based on the decoded alert messages.

- **ib_insync:** TBOT uses the ib_insync API, which is a third-party Python library that provides a high-level interface to the official TWS API from Interactive Brokers. Ib_insync simplifies the complexities of the TWS API and offers a more Pythonic way to interact with Interactive Brokers.

- **Order placement and tracking:** TBOT validates and places orders with Interactive Brokers based on the decoded alert messages. It supports various order types such as market orders, stop orders, limit orders, stop-limit orders, bracket orders, and attached orders. TBOT also tracks the status of placed orders and provides monitoring and management capabilities.

- **Event handling and database management:** TBOT utilizes the event handling functionality of ib_insync to track order status updates and handle errors reported by Interactive Brokers. It uses a database (e.g., SQLite3) to store and manage information related to alerts, orders, and errors, allowing for effective order tracking and error handling.

Overall, TBOT enhances the capabilities of Interactive Brokers by integrating with TradingView and providing back-testing and forward-testing functionalities. It enables traders to develop and execute trading strategies based on TradingView's tools while leveraging the execution capabilities of Interactive Brokers.


### The Architecture of TBOT

TBOT is built using a combination of the Subscriber of the Pub/Sub pattern and the Observer pattern. It uses the Subscriber to receive messages from a Redis Stream or Pub/Sub and the Observer to deliver messages to Interactive Brokers, message applications, and the watchdog. TBOT is designed to be a flexible and extensible system that can be customized to meet the needs of various trading strategies and workflows. The architecture of TBOT enables it to be easily integrated with other systems and services, making it a powerful tool for automating trading processes.

![The-Architecture-of-TBOT](https://github.com/PlusGenie/tbot-tradingboat/assets/1986788/17e80fd5-e740-4cf1-acb1-93bbe225e33b)


### TBOT on TradingBoat

TradingBoat is a platform that includes Nginx/Ngrok, Flask, Redis, TBOT, and IB Gateway.

TBOT serves as the message decoder and order placement tool, and is the brain of TradingBoat. We can refer to it as TBOT on TradingBoat.

![TBOT-on-TradingBoat](https://user-images.githubusercontent.com/1986788/226757087-16d96ad4-30f6-4310-bc70-eec3cc38dea9.png)

<mark>If you install TradingBoat using Docker from [https://github.com/PlusGenie/ib-gateway-docker](https://github.com/PlusGenie/ib-gateway-docker), the TBOT application will be automatically installed within Docker containers.</mark>

<mark>This page provides instructions for standalone installation of the TBOT application.</mark>

<mark>If you are new to the TBOT application, we recommend considering the Docker installation from [https://github.com/PlusGenie/ib-gateway-docker](https://github.com/PlusGenie/ib-gateway-docker) to gain an overall understanding.</mark>


## Preparing for Installation of TBOT Application
To begin, follow the steps below to download, install, set up environment variables, and run the TBOT application.

### Set up the Environment
Start by installing Python +3.9, assuming you are using Ubuntu 22.04.

```console
apt-get install -y python3.9 python3.9-venv python3.9-dev python3.9-distutils python3-pip
```

It is recommended to install the libtmux and loguru libraries globally if you plan to use tbottmux.
```console
pip install libtmux loguru
```

### Create a Non-Root User
Create a non-root user with a home directory using the following command:
```console
useradd -m tbot
```

## Downloading and Setting Up TBOT Application
### Create a Python Virtual Environment
Create the necessary directory structure and clone the TBOT repository:

```console
mkdir -p /home/tbot/develop/github
git clone https://github.com/PlusGenie/tbot-tradingboat.git
```

Navigate to the TBOT directory and set up a Python virtual environment:
```console
cd /home/tbot/develop/github/tbot-tradingboat
python3 -m venv .venv
source .venv/bin/activate
```

### Install Dependencies
```console
pip install -r requirements.txt
```

### Install Dependencies
Install TBOT as an editable package using the following command:
```console
pip install -e .
```

## Configuring the TBOT Application
To configure the default environment variables for TBOT, copy the example dotenv file:

![tbot_tradingboat_environment](https://github.com/PlusGenie/tbot-tradingboat/assets/1986788/39ae2f49-dc14-4c0c-8fe0-1fbb830343a8)

```console
cp src/tbot_tradingboat/utils/examples/dotenv ~/.env
```
Open the .env file and update the necessary environment variables. For example, you may need to update TBOT_IBKR_PORT and TBOT_IBKR_IPADDR based on your setup.

For more details, please refer to the chapter [How to Use a DotEnv File to Control TradingBoat](https://tbot.plusgenie.com/how-to-use-a-dotenv-file-to-control-tradingboat-2)

## Running the TBOT Application
To start the TBOT application, use the following command:
```console
python src/tbot_tradingboat/main.py
```

## Conclusion
By following these steps, you should now have the TBOT application installed and running. Feel free to explore and configure additional features based on your requirements.
For more details on utilizing [a DotEnv file to control TradingBoat](https://tbot.plusgenie.com/how-to-use-a-dotenv-file-to-control-tradingboat-2), please refer to the corresponding chapter.


## TBOT Warning: For Educational Purposes Only

<code style="color : orangered">
All software provided here is intended for educational purposes only. Please be aware that any financial trading involves inherent risks and may result in financial losses. This is for educational purposes only. We strongly advise testing it solely with an Interactive Brokers Paper Account.
</code>

## Reference
* [TBOT on TradingBoat: Unleash the Power of Automated Trading](https://tbot.plusgenie.com/unleash-the-power-of-automated-trading)
* [Brief Introduction to Trading Systems: Overcoming Challenges and Unlocking Potential #1](https://tbot.plusgenie.com/brief-introduction-to-trading-systems-overcoming-challenges-and-unlocking-potential)
* [Brief Introduction to Trading Systems: Overcoming Challenges and Unlocking Potential #2](https://tbot.plusgenie.com/brief-introduction-to-trading-systems-overcoming-challenges-and-unlocking-potential-2)
* [Brief Introduction to Trading Systems: Overcoming Challenges and Unlocking Potential #3](https://tbot.plusgenie.com/brief-introduction-to-trading-systems-overcoming-challenges-and-unlocking-potential-3)
* [A Quick Demo of Trading Robot](https://tbot.plusgenie.com/a-quick-demo-of-tbot-on-tradingboat)
---
* [Harnessing the Power of Redis for Efficient Trading Operations: A Detailed Look at Redis Pub/Sub and Redis Stream - Part 1](https://tbot.plusgenie.com/harnessing-the-power-of-redis-for-efficient-trading-operations-a-detailed-look-at-redis-pub-sub-and-redis-stream)

* [Harnessing the Power of Redis for Efficient Trading Operations: A Detailed Look at Redis Pub/Sub and Redis Stream- Part 2](https://tbot.plusgenie.com/harnessing-the-power-of-redis-for-efficient-trading-operations-a-detailed-look-at-redis-pub-sub-and-redis-stream-part-2/)

* [Optimizing Execution Time: Improving TradingView to Interactive Brokers Delay with AWS Cloud](https://tbot.plusgenie.com/optimizing-execution-time-improving-tradingview-to-interactive-brokers-delay-with-aws-cloud)

* [Decoding TradingView Alerts and Mastering ib_insync: A Comprehensive Guide](https://tbot.plusgenie.com/decoding-tradingview-alerts-and-mastering-ib_insync-a-comprehensive-guide)<br>
---
* [The extensive instructions and invaluable insights, enabling you to effectively leverage TBOT for your trading activities](https://www.udemy.com/course/simple-and-fast-trading-robot-setup-with-docker-tradingview/)
