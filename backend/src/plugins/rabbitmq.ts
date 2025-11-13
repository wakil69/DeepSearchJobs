import fp from "fastify-plugin";
import amqp from "amqplib";
import * as dotenv from "dotenv";

dotenv.config();

export default fp(async (fastify) => {
  const url = process.env.RABBITMQ_URL || "amqp://localhost:5672";

  fastify.log.info(`Connecting to RabbitMQ at ${url}`);

  const connection = await amqp.connect(url);
  const channel = await connection.createChannel();

  fastify.addHook("onClose", async () => {
    fastify.log.info("Closing RabbitMQ connection...");
    await channel.close();
    await connection.close();
  });

  const publish = async (queue: string, message: any) => {
    await channel.assertQueue(queue, { durable: true });
    channel.sendToQueue(queue, Buffer.from(JSON.stringify(message)), {
      persistent: true,
    });
  };

  fastify.decorate("rabbitmq", { connection, channel, publish });

  fastify.log.info("RabbitMQ connected and registered");
});
